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
from extract import PROSPECT_ONLY_FIELDS, extract_from_transcript
from formatter import write_outputs
from ingest import ingest
from prospect_matching import ProspectCandidate, find_matching_prospect
from supabase_client import (
    download_raw_file,
    get_claims_by_state,
    get_claims_for_job,
    get_open_claims_for_prospect,
    get_org_prospect_candidates,
    get_prospect,
    insert_claims,
    insert_recommendation,
    update_claim,
    update_job,
    update_prospect,
    upload_output_file,
    upsert_prospect,
)
from transcribe_deepgram import transcribe_with_deepgram
from transcribe_gemini import transcribe_with_gemini
from reconcile_state import ExistingClaim, NewClaim, reconcile_claims
from recommend import recommend_next_action
from score import score_prospect
from verify import verify_claims_batch

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
                "persona_overview": prospect_participant.persona_overview,
            }.items()
            if v is not None
        }
        if persona_fields:
            prospect_id = upsert_prospect(org_id, prospect_id, persona_fields)

    written_claims: list[dict] = []
    if prospect_id:
        # interest/objection/pain_point/risk_signal are specifically about
        # assessing the PROSPECT — filtered to their speaker_label.
        # commitment/open_question matter regardless of who raised them
        # (an open loop is an open loop no matter who left it open).
        relevant_items = [
            item for item in result.items
            if item.field not in PROSPECT_ONLY_FIELDS or item.speaker_label == prospect_participant.speaker_label
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
    """One batched call per round instead of one call per claim — see
    verify.py's docstring for why this matters (Gemini's daily free-tier
    quota is trivially exhausted by the per-claim design on even a
    handful of test jobs)."""
    updates = verify_claims_batch(transcript_text, claims, GEMINI)
    for claim, update in zip(claims, updates):
        update_claim(
            claim["id"],
            status=update.status,
            text=update.text,
            evidence_line=update.evidence_line,
            retries=update.retries,
        )
        print(f"[job {job_id}] [verify] claim {claim['id']} ({claim['field']}) -> {update.status} (retries={update.retries})")


def _run_reconcile_stage(job_id: str, prospect_id: str) -> None:
    """The actual belief-tracking step: does each claim from this job
    match something already on file for this prospect (update, don't
    duplicate), or is it genuinely new? Does anything here explicitly
    resolve an old claim? Silence never counts as resolution."""
    fresh_claims = get_claims_for_job(job_id)
    existing_open = get_open_claims_for_prospect(prospect_id, exclude_job_id=job_id)

    if not fresh_claims:
        return

    existing_wrapped = [ExistingClaim(id=c["id"], field=c["field"], text=c["text"]) for c in existing_open]
    new_wrapped = [NewClaim(id=c["id"], field=c["field"], text=c["text"]) for c in fresh_claims]

    outcome = reconcile_claims(existing_wrapped, new_wrapped, GEMINI)
    for note in outcome.notes:
        print(f"[job {job_id}] [reconcile] {note}")

    existing_by_id = {c["id"]: c for c in existing_open}
    new_by_id = {c["id"]: c for c in fresh_claims}

    for match in outcome.matches:
        if match.matches_existing_id and match.matches_existing_id in existing_by_id:
            existing_claim = existing_by_id[match.matches_existing_id]
            new_claim = new_by_id[match.new_claim_id]
            # the kept row (existing) gets updated to the latest phrasing,
            # its job_id becomes "most recently confirmed by", mention count grows
            update_claim(
                existing_claim["id"],
                text=new_claim["text"],
                evidence_line=new_claim.get("evidence_line"),
                job_id=job_id,
                mention_count=(existing_claim.get("mention_count") or 1) + 1,
            )
            # the new row is a duplicate — kept for history, marked superseded, not deleted
            update_claim(match.new_claim_id, state="superseded", superseded_by=existing_claim["id"])
            print(f"[job {job_id}] [reconcile] claim {match.new_claim_id} matched existing {existing_claim['id']} — merged, not duplicated")
        else:
            update_claim(match.new_claim_id, state="open", first_job_id=job_id, mention_count=1)
            print(f"[job {job_id}] [reconcile] claim {match.new_claim_id} is genuinely new")

    for resolved_id in outcome.resolved_existing_ids:
        if resolved_id in existing_by_id:
            update_claim(resolved_id, state="resolved")
            print(f"[job {job_id}] [reconcile] claim {resolved_id} marked resolved")


def _run_score_stage(job_id: str, prospect_id: str) -> None:
    """Deterministic rubric scoring (zero API calls) + one evidence-
    grounded narrative + its own bounded verify pass."""
    open_claims = get_claims_by_state(prospect_id, "open")
    resolved_claims = get_claims_by_state(prospect_id, "resolved")

    result, narrative = score_prospect(open_claims, resolved_claims, GEMINI)

    update_prospect(
        prospect_id,
        interest_score=result.interest_score,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        score_summary=narrative.summary,
        score_status=narrative.status,
        score_breakdown={
            "interest_factors": [
                {"label": f.label, "points": f.points, "claim_ids": f.claim_ids} for f in result.interest_factors
            ],
            "risk_factors": [
                {"label": f.label, "points": f.points, "claim_ids": f.claim_ids} for f in result.risk_factors
            ],
        },
    )
    print(
        f"[job {job_id}] [score] interest={result.interest_score} risk={result.risk_score} "
        f"({result.risk_level}) narrative={narrative.status} (retries={narrative.retries})"
    )


def _run_recommend_stage(job_id: str, prospect_id: str) -> None:
    """Synthesizes the current open claims + just-computed score into a
    concrete next step. No separate verify stage here — see recommend.py's
    docstring for why (everything feeding it is already verified)."""
    prospect = get_prospect(prospect_id)
    if not prospect:
        print(f"[job {job_id}] [recommend] couldn't load prospect {prospect_id}, skipping")
        return

    open_claims = get_claims_by_state(prospect_id, "open")
    rec = recommend_next_action(prospect, open_claims, GEMINI)

    insert_recommendation(
        {
            "prospect_id": prospect_id,
            "job_id": job_id,
            "recommended_opening": rec.recommended_opening,
            "next_best_action": rec.next_best_action,
            "grounding_claim_ids": rec.grounding_claim_ids,
        }
    )
    print(f"[job {job_id}] [recommend] next_best_action: {rec.next_best_action}")


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
            if prospect_id:
                _run_reconcile_stage(job_id, prospect_id)
                _run_score_stage(job_id, prospect_id)
                _run_recommend_stage(job_id, prospect_id)

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
