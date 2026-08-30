"""
verify — a second, independent LLM checks every claim extract() produced
against the actual transcript, in ONE batched call per round instead of
one call per claim. This matters for two real reasons, not just cost:

  1. Gemini's free tier has a hard daily request cap. The original
     per-claim design could burn 10-15+ calls on a single 3-claim job
     (1 verify + up to 2 retry rounds x 2 calls each, PER claim) —
     trivially exhausting a daily quota during normal testing.
  2. It's simply wasteful: there's no reason to pay for N separate round
     trips when one call can check N claims against the same transcript
     at once.

The batched design bounds total calls to roughly 2 x (MAX_RETRIES + 1)
for the ENTIRE job, regardless of how many claims it has — 3 claims and
30 claims cost about the same number of API calls.

Two things get checked per claim, same as before:
  1. Is the cited evidence actually IN the transcript?
  2. Does that evidence actually SUPPORT the claim as stated?

The orchestration loop (verify_claims_batch_core) is pure control flow,
parameterized over the two network-calling functions — fully testable
without hitting a real API by injecting fake batch functions that return
a scripted sequence of outcomes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from config import GeminiSettings

MAX_RETRIES = 2

VERIFY_BATCH_PROMPT_TEMPLATE = """You are fact-checking several claims extracted from a business conversation transcript.

For EACH claim below, check two things against the full transcript:
1. Does the cited evidence actually appear in the transcript (word-for-word or a very close paraphrase)? Do not accept a fabricated or invented quote.
2. Does that evidence genuinely support the claim as stated? Do not accept a claim that overstates, misreads, or contradicts what the evidence actually says.

Claims to check (numbered):
{claims_block}

Return ONLY valid JSON, no markdown fences, no commentary — a JSON array with EXACTLY {n} entries, one per claim, IN THE SAME ORDER as listed above:
[
  {{"verified": true, "reason": "brief explanation, especially if false"}}
]

Full transcript:
\"\"\"
{transcript}
\"\"\"
"""

REEXTRACT_BATCH_PROMPT_TEMPLATE = """Several claims extracted from this transcript were rejected during verification. For EACH one, look at the transcript again and try to find a CORRECTED claim of the same type, fixing the stated problem. If you genuinely cannot find valid evidence for a claim, say so explicitly rather than inventing one.

Claims to correct (numbered):
{claims_block}

Return ONLY valid JSON, no markdown fences — a JSON array with EXACTLY {n} entries, one per claim, IN THE SAME ORDER as listed above:
[
  {{"found": true, "text": "corrected claim or null", "evidence": "exact quote or null"}}
]

Full transcript:
\"\"\"
{transcript}
\"\"\"
"""


@dataclass
class VerifyResult:
    verified: bool
    reason: str | None


@dataclass
class ReextractResult:
    found: bool
    text: str | None
    evidence: str | None


@dataclass
class ClaimUpdate:
    status: str  # "confirmed" | "partial"
    text: str
    evidence_line: str | None
    retries: int
    note: str | None = None


def build_verify_batch_prompt(transcript: str, claims: list[dict]) -> str:
    lines = [
        f"[{i + 1}] type: {c['field']} | claim: \"{c['text']}\" | evidence: \"{c.get('evidence') or ''}\""
        for i, c in enumerate(claims)
    ]
    return VERIFY_BATCH_PROMPT_TEMPLATE.format(claims_block="\n".join(lines), n=len(claims), transcript=transcript)


def build_reextract_batch_prompt(transcript: str, claims: list[dict]) -> str:
    lines = [
        f"[{i + 1}] type: {c['field']} | previous claim: \"{c['text']}\" | previous evidence: \"{c.get('evidence') or ''}\" | rejection reason: \"{c.get('reason') or 'unspecified'}\""
        for i, c in enumerate(claims)
    ]
    return REEXTRACT_BATCH_PROMPT_TEMPLATE.format(claims_block="\n".join(lines), n=len(claims), transcript=transcript)


def _extract_json(raw_text: str):
    raw_text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*\]|\{.*\})\s*```", raw_text, re.DOTALL)
    if fenced:
        raw_text = fenced.group(1)
    return json.loads(raw_text)


def parse_verify_batch_response(raw_text: str, expected_count: int) -> list[VerifyResult]:
    parsed = _extract_json(raw_text)
    if not isinstance(parsed, list):
        parsed = [parsed]
    results = [VerifyResult(verified=bool(item.get("verified")), reason=item.get("reason")) for item in parsed]
    # Defensive: if the model returned fewer entries than claims sent, pad
    # with "not verified" rather than crash or silently misalign the rest —
    # a missing result should trigger a retry, not be treated as confirmed.
    while len(results) < expected_count:
        results.append(VerifyResult(verified=False, reason="no result returned for this claim"))
    return results[:expected_count]


def parse_reextract_batch_response(raw_text: str, expected_count: int) -> list[ReextractResult]:
    parsed = _extract_json(raw_text)
    if not isinstance(parsed, list):
        parsed = [parsed]
    results = [
        ReextractResult(found=bool(item.get("found")), text=item.get("text"), evidence=item.get("evidence"))
        for item in parsed
    ]
    while len(results) < expected_count:
        results.append(ReextractResult(found=False, text=None, evidence=None))
    return results[:expected_count]


def verify_claims_batch_core(
    transcript: str,
    claims: list[dict],
    verify_batch_fn: Callable[[str, list[dict]], list[VerifyResult]],
    reextract_batch_fn: Callable[[str, list[dict]], list[ReextractResult]],
    max_retries: int = MAX_RETRIES,
) -> list[ClaimUpdate]:
    """Pure batched retry loop. `claims` is a list of dicts with at least
    field/text/evidence_line/retries. Returns one ClaimUpdate per input
    claim, in the same order — every claim resolves to confirmed or
    partial, none left pending, none silently dropped."""
    working = [
        {
            "field": c["field"], "text": c["text"], "evidence": c.get("evidence_line"),
            "retries": c.get("retries", 0), "status": "pending", "note": None,
        }
        for c in claims
    ]
    pending_indices = list(range(len(working)))

    while pending_indices:
        batch = [working[i] for i in pending_indices]
        results = verify_batch_fn(transcript, batch)

        to_reextract: list[int] = []
        for idx, result in zip(pending_indices, results):
            if result.verified:
                working[idx]["status"] = "confirmed"
            elif working[idx]["retries"] >= max_retries:
                working[idx]["status"] = "partial"
                working[idx]["note"] = f"retries exhausted: {result.reason}"
            else:
                working[idx]["_reject_reason"] = result.reason
                to_reextract.append(idx)

        if not to_reextract:
            break

        reextract_batch = [{**working[i], "reason": working[i].get("_reject_reason")} for i in to_reextract]
        reextract_results = reextract_batch_fn(transcript, reextract_batch)

        next_pending: list[int] = []
        for idx, re_result in zip(to_reextract, reextract_results):
            working[idx]["retries"] += 1
            if re_result.found and re_result.text and re_result.evidence:
                working[idx]["text"] = re_result.text
                working[idx]["evidence"] = re_result.evidence
                next_pending.append(idx)
            else:
                working[idx]["status"] = "partial"
                working[idx]["note"] = "no corrected claim found on retry"

        pending_indices = next_pending

    return [
        ClaimUpdate(status=w["status"], text=w["text"], evidence_line=w["evidence"], retries=w["retries"], note=w["note"])
        for w in working
    ]


def _call_gemini_verify_batch(transcript: str, claims: list[dict], settings: GeminiSettings) -> list[VerifyResult]:
    from google import genai

    client = genai.Client(api_key=settings.api_key)
    response = client.models.generate_content(
        model=settings.model, contents=build_verify_batch_prompt(transcript, claims)
    )
    return parse_verify_batch_response(response.text, expected_count=len(claims))


def _call_gemini_reextract_batch(transcript: str, claims: list[dict], settings: GeminiSettings) -> list[ReextractResult]:
    from google import genai

    client = genai.Client(api_key=settings.api_key)
    response = client.models.generate_content(
        model=settings.model, contents=build_reextract_batch_prompt(transcript, claims)
    )
    return parse_reextract_batch_response(response.text, expected_count=len(claims))


def verify_claims_batch(transcript: str, claims: list[dict], settings: GeminiSettings) -> list[ClaimUpdate]:
    """Thin wrapper around verify_claims_batch_core with real Gemini
    calls — the retry/batching logic itself lives in the core function
    and is what's unit-tested."""
    return verify_claims_batch_core(
        transcript,
        claims,
        verify_batch_fn=lambda t, c: _call_gemini_verify_batch(t, c, settings),
        reextract_batch_fn=lambda t, c: _call_gemini_reextract_batch(t, c, settings),
    )
