"""
main — FastAPI app for the deployed primer backend.

One real endpoint: POST /webhook/job-created, called by a Supabase Database
Webhook the moment a new row lands in the `jobs` table. Runs:

    download from Storage -> ingest -> [deepgram, gemini] in parallel
        -> compare -> format -> upload results -> update job row

Processing happens in a background task so the webhook gets an immediate
200 response (Supabase's webhook has its own timeout — we don't want a
30-minute video transcription blocking that response).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from .compare import CompareResult, FinalSegment, compare_transcripts
from .config import COMPARE, DEEPGRAM, GEMINI, WEBHOOK
from .formatter import write_outputs
from .ingest import ingest
from .supabase_client import download_raw_file, update_job, upload_output_file
from .transcribe_deepgram import transcribe_with_deepgram
from .transcribe_gemini import transcribe_with_gemini

app = FastAPI(title="primer backend")


@app.get("/health")
def health():
    """Render (and you) can hit this to confirm the service is actually up."""
    return {"status": "ok"}


def _text_passthrough(raw_text: str) -> CompareResult:
    seg = FinalSegment(start=0.0, end=0.0, speaker="TEXT", text=raw_text, status="agreed")
    return CompareResult(segments=[seg], disagreement_count=0, agreement_count=1)


def process_job(job_id: str, storage_path: str) -> None:
    work_dir = Path(tempfile.mkdtemp(prefix=f"job_{job_id}_"))
    try:
        update_job(job_id, status="processing")

        local_path = download_raw_file(storage_path, work_dir)
        ingested = ingest(local_path, work_dir=work_dir)

        if ingested.artifact_type == "text":
            result = _text_passthrough(ingested.raw_text or "")
        else:
            print(f"[job {job_id}] running deepgram and gemini in parallel...")
            with ThreadPoolExecutor(max_workers=2) as pool:
                dg_future = pool.submit(transcribe_with_deepgram, ingested.audio_path, DEEPGRAM)
                gm_future = pool.submit(transcribe_with_gemini, ingested.original_path, GEMINI)

                dg_result = dg_future.result()
                for note in dg_result.notes:
                    print(f"[job {job_id}] [deepgram] {note}")

                try:
                    gm_result = gm_future.result()
                    gm_segments = gm_result.segments
                except Exception as exc:  # noqa: BLE001
                    print(f"[job {job_id}] [gemini] path failed: {exc}")
                    gm_segments = []

            if gm_segments:
                result = compare_transcripts(dg_result.segments, gm_segments, COMPARE, GEMINI)
            else:
                result = CompareResult(
                    segments=[
                        FinalSegment(s.start, s.end, s.speaker, s.text, "low_confidence", whisperx_text=s.text)
                        for s in dg_result.segments
                    ],
                    disagreement_count=len(dg_result.segments),
                    agreement_count=0,
                    notes=["gemini path unavailable — no cross-check was possible for this run"],
                )

        md_path, json_path = write_outputs(result, local_path.name, work_dir)

        stem = Path(storage_path).stem
        upload_output_file(md_path, f"{stem}/{md_path.name}")
        upload_output_file(json_path, f"{stem}/{json_path.name}")

        update_job(
            job_id,
            status="done",
            transcript_md_path=f"{stem}/{md_path.name}",
            transcript_json=json.loads(json_path.read_text()),
        )
        print(f"[job {job_id}] done")

    except Exception as exc:  # noqa: BLE001 — a failed job must still update its own status, never hang as "processing" forever
        print(f"[job {job_id}] FAILED: {exc}\n{traceback.format_exc()}")
        try:
            update_job(job_id, status="failed", error=str(exc))
        except Exception as update_exc:  # noqa: BLE001 — the failure-reporter must never itself throw uncaught
            print(f"[job {job_id}] ALSO FAILED to record failure status: {update_exc}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/webhook/job-created")
async def job_created_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_secret: str | None = Header(default=None),
):
    if WEBHOOK.secret and x_webhook_secret != WEBHOOK.secret:
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    payload = await request.json()
    # Supabase Database Webhook payload shape: {"type": "INSERT", "table": "jobs", "record": {...}, ...}
    record = payload.get("record") or payload.get("new") or {}
    job_id = record.get("id")
    storage_path = record.get("file_path")

    if not job_id or not storage_path:
        raise HTTPException(status_code=400, detail="payload missing id/file_path")

    background_tasks.add_task(process_job, job_id, storage_path)
    return {"accepted": True, "job_id": job_id}
