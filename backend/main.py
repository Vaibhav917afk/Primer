"""
main — FastAPI app for the deployed primer backend.

One real endpoint: POST /webhook/job-created, called by a Supabase Database
Webhook (via a SQL trigger executing supabase_functions.http_request) the
moment a new row lands in the `jobs` table. Runs:

    download from Storage -> ingest -> [deepgram, gemini] in parallel
        -> compare -> extract (participants/interests/objections/commitments,
           SPEAKER-LABELED transcript so rep vs prospect can be told apart)
        -> upsert prospect -> write claims -> verify claims
        -> format transcript -> upload results -> update job row

The transcript handed to extract() preserves per-segment speaker labels
(SPEAKER_00: ..., SPEAKER_01: ...) — an earlier version flattened all
segments into one undifferentiated block of text, which made it
impossible for extract to tell the rep and the prospect apart, or to
attribute an objection/interest to the right person. That's fixed here.

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


def _build_speaker_labeled_text(segments) -> str:
    """The single most important line in this file: WITHOUT speaker labels
    preserved here, extract() cannot tell who said what, cannot identify
    rep vs prospect, and cannot attribute an objection to the right person.
    This was a real, silent bug in an earlier version."""
    lines = []
    current_speaker = None
    for seg in segments:
        if not seg.text:
            continue
        if seg.speaker != current_speaker:
            lines.append(f"{seg.speaker}: {seg.text}")
            current_speaker = seg.speaker
        else:
            lines[-1] += f" {seg.text}"
    return "\n".join(lines)


def _run_extract_stage(job_id: str, org_id: str | None, existing_prospect_id: str | None, transcript_text: str):
    if not transcript_text.strip():
        print(f"[job {job_id}] nothing to extract — empty transcript")
        return existing_prospect_id, [], {"topics": [], "entities": []}

    result = extract_from_transcript(transcript_text, GEMINI)
    for note in result.notes:
        print(f"[job {job_id}] [extract] {note}")

    extra_meta = {
        "topics": result.topics,
        "entities": [{"text": e.text, "type": e.type, "evidence": e.evidence_line} for e in result.entities],
        "participants": [
            {"speaker_label": p.speaker_label, "name": p.name, "role_in_call": p.role_in_call,
             "role_title": p.role_title, "company": p.company}
            for p in result.participants
        ],
    }

    prospect_participant = result.prospect()
    if prospect_participant is None:
        print(f"[job {job_id}] [extract] no speaker was identified as the prospect (participants: {len(result.participants)}) — nothing linked")
        return existing_prospect_id, [], extra_meta

    prospect_id = existing_prospect_id
    if org_id:
        if not prospect_id:
            candidates_raw = get_org_prospect_candidates(org_id)
            candidates = [
                ProspectCandidate(id=c["id"], name=c.get("name"), company=c.get("company"), email=c.get("email"))
                for c in candidates_raw
            ]
            prospect_id = find_matching_prospect(prospect_participant, candidates)

        persona_fields = {
            k: v
            for k, v in {
                "name": prospect_participant.name,
                "role_title": prospect_participant.role_title,
                "company": prospect_participant.company,
                "email": prospect_participant.email,
            }.items()
            if v is not None
        }
        if persona_fields:
            prospect_id = upsert_prospect(org_id, prospect_id, persona_fields)

    written_claims: list[dict] = []
    if prospect_id:
        # interests/objections are specifically the PROSPECT's — filter to
        # their speaker_label. commitments can reasonably come from either
        # party (the rep committing to send a proposal matters just as
        # much as the prospect committing to review it), so those are kept
        # regardless of who said them.
        relevant_items = [
            item for item in result.items
            if item.field == "commitment" or item.speaker_label == prospect_participant.speaker_label
        ]

        claim_rows = [
            {
                "job_id": job_id,
                "prospect_id": prospect_id,
                "field": item.field,
                "text": item.text,
                "evidence_line": item.evidence_line,
                "speaker_label": item.speaker_label,
                "status": "pending",
                "retries": 0,
            }
            for item in relevant_items
        ]
        written_claims = insert_claims(claim_rows)
        print(f"[job {job_id}] [extract] wrote {len(written_claims)} claims, prospect_id={prospect_id}")
    else:
        print(f"[job {job_id}] [extract] prospect identified but no org_id on this job — nothing could be linked")

    return prospect_id, written_claims, extra_meta


def _run_verify_stage(job_id: str, transcript_text: str, claims: list[dict]) -> None:
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

        speaker_labeled_text = _build_speaker_labeled_text(result.segments)
        prospect_id, written_claims, extra_meta = _run_extract_stage(job_id, org_id, existing_prospect_id, speaker_labeled_text)

        if written_claims:
            _run_verify_stage(job_id, speaker_labeled_text, written_claims)

        md_path, json_path = write_outputs(result, local_path.name, work_dir)

        stem = Path(storage_path).stem
        upload_output_file(md_path, f"{stem}/{md_path.name}")
        upload_output_file(json_path, f"{stem}/{json_path.name}")

        transcript_json = json.loads(json_path.read_text())
        transcript_json.update(extra_meta)

        update_job(
            job_id,
            status="done",
            prospect_id=prospect_id,
            transcript_md_path=f"{stem}/{md_path.name}",
            transcript_json=transcript_json,
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
