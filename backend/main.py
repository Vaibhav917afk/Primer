"""
main — FastAPI app for the deployed primer backend.

One real endpoint: POST /webhook/job-created, called by a Supabase Database
Webhook (via a SQL trigger executing supabase_functions.http_request) the
moment a new row lands in the `jobs` table. Runs:

    download from Storage -> ingest -> [deepgram, gemini] in parallel
        -> compare -> extract (persona/interests/objections/commitments)
        -> upsert prospect -> write claims -> verify claims
        -> format transcript -> upload results -> update job row

org_id/prospect_id are read directly from the webhook payload (Supabase
includes the full inserted row as `record`) rather than via a follow-up
get_job() call — that follow-up call raced against Supabase's own
read-after-write consistency and intermittently came back without org_id.

Processing happens in a plain daemon thread, not FastAPI's BackgroundTasks —
BackgroundTasks was confirmed not to actually execute on this deployment.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request

from compare import CompareResult, FinalSegment, compare_transcripts
from config import COMPARE, DEEPGRAM, GEMINI, WEBHOOK
from extract import extract_from_transcript
from formatter import write_outputs
from ingest import ingest
from prospect_matching import ProspectCandidate, find_matching_prospect
from supabase_client import (
    download_raw_file,
    get_org_prospect_candidates,
    insert_claims,
    update_claim,
    update_job,
    upload_output_file,
    upsert_prospect,
)
from transcribe_deepgram import transcribe_with_deepgram
from transcribe_gemini import transcribe_with_gemini
from verify import verify_claim

app = FastAPI(title="primer backend")


@app.get("/health")
def health():
    return {"status": "ok"}


def _text_passthrough(raw_text: str) -> CompareResult:
    seg = FinalSegment(start=0.0, end=0.0, speaker="TEXT", text=raw_text, status="agreed")
    return CompareResult(segments=[seg], disagreement_count=0, agreement_count=1)


def _run_extract_stage(job_id: str, org_id: str | None, existing_prospect_id: str | None, transcript_text: str):
    if not transcript_text.strip():
        print(f"[job {job_id}] nothing to extract — empty transcript")
        return existing_prospect_id, []

    result = extract_from_transcript(transcript_text, GEMINI)
    for note in result.notes:
        print(f"[job {job_id}] [extract] {note}")

    prospect_id = existing_prospect_id
    if org_id:
        if not prospect_id:
            candidates_raw = get_org_prospect_candidates(org_id)
            candidates = [
                ProspectCandidate(id=c["id"], name=c.get("name"), company=c.get("company"), email=c.get("email"))
                for c in candidates_raw
            ]
            prospect_id = find_matching_prospect(result.persona, candidates)

        persona_fields = {
            k: v
            for k, v in {
                "name": result.persona.name,
                "role_title": result.persona.role,
                "company": result.persona.company,
                "email": result.persona.email,
            }.items()
            if v is not None
        }
        if persona_fields:
            prospect_id = upsert_prospect(org_id, prospect_id, persona_fields)

    written_claims: list[dict] = []
    if prospect_id:
        claim_rows = [
            {
                "job_id": job_id,
                "prospect_id": prospect_id,
                "field": item.field,
                "text": item.text,
                "evidence_line": item.evidence_line,
                "status": "pending",
                "retries": 0,
            }
            for item in result.items
        ]
        written_claims = insert_claims(claim_rows)
        print(f"[job {job_id}] [extract] wrote {len(written_claims)} claims, prospect_id={prospect_id}")
    else:
        print(f"[job {job_id}] [extract] no persona info extracted — {len(result.items)} items couldn't be linked to a prospect")

    return prospect_id, written_claims


def _run_verify_stage(job_id: str, transcript_text: str, claims: list[dict]) -> None:
    """Independently double-checks every claim extract() wrote. Each claim
    resolves to confirmed or partial — never left stuck as pending, never
    silently dropped."""
    for claim in claims:
        update = verify_claim(transcript_text, claim, GEMINI)
        update_claim(
            claim["id"],
            status=update.status,
            text=update.text,
            evidence_line=update.evidence_line,
            retries=update.retries,
        )
        print(f"[job {job_id}] [verify] claim {claim['id']} ({claim['field']}) -> {update.status} (retries={update.retries})")


def process_job(job_id: str, storage_path: str, org_id: str | None = None, existing_prospect_id: str | None = None) -> None:
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

        full_text = " ".join(seg.text for seg in result.segments if seg.text)
        prospect_id, written_claims = _run_extract_stage(job_id, org_id, existing_prospect_id, full_text)

        if written_claims:
            _run_verify_stage(job_id, full_text, written_claims)

        md_path, json_path = write_outputs(result, local_path.name, work_dir)

        stem = Path(storage_path).stem
        upload_output_file(md_path, f"{stem}/{md_path.name}")
        upload_output_file(json_path, f"{stem}/{json_path.name}")

        update_job(
            job_id,
            status="done",
            prospect_id=prospect_id,
            transcript_md_path=f"{stem}/{md_path.name}",
            transcript_json=json.loads(json_path.read_text()),
        )
        print(f"[job {job_id}] done")

    except Exception as exc:  # noqa: BLE001
        print(f"[job {job_id}] FAILED: {exc}\n{traceback.format_exc()}")
        try:
            update_job(job_id, status="failed", error=str(exc))
        except Exception as update_exc:  # noqa: BLE001
            print(f"[job {job_id}] ALSO FAILED to record failure status: {update_exc}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/webhook/job-created")
async def job_created_webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
):
    if WEBHOOK.secret and x_webhook_secret != WEBHOOK.secret:
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    payload = await request.json()
    record = payload.get("record") or payload.get("new") or {}
    job_id = record.get("id")
    storage_path = record.get("file_path")
    org_id = record.get("org_id")
    prospect_id = record.get("prospect_id")

    if not job_id or not storage_path:
        raise HTTPException(status_code=400, detail="payload missing id/file_path")

    thread = threading.Thread(target=process_job, args=(job_id, storage_path, org_id, prospect_id), daemon=True)
    thread.start()
    return {"accepted": True, "job_id": job_id}
