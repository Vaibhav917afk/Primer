"""
verify — a second, independent LLM checks every claim extract() produced
against the actual transcript. Not the same call grading its own work —
a fresh Gemini call with no memory of how the claim was originally derived,
only the claim, its cited evidence, and the transcript to check both against.

Two things get checked together:
  1. Is the cited evidence actually IN the transcript (word-for-word or a
     close paraphrase) — catches a fabricated quote.
  2. Does that evidence actually SUPPORT the claim as stated — catches a
     claim that overstates or misreads real evidence.

If a claim fails and still has retries left, one targeted re-extraction
attempt runs — asking specifically for a corrected claim of that field
type, given the rejection reason — and the result gets re-verified. This
loop is hard-bounded by MAX_RETRIES: every claim ends at either
"confirmed" or "partial", never stuck retrying forever and never silently
dropped.

The retry loop itself (verify_claim) is pure control flow, parameterized
over the two network-calling functions — this is what makes it fully
testable without hitting a real API: tests inject fake verify/reextract
functions that return a scripted sequence of outcomes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from config import GeminiSettings

MAX_RETRIES = 2

VERIFY_PROMPT_TEMPLATE = """You are fact-checking a claim extracted from a business conversation transcript.

Claim type: {field}
Claim: "{text}"
Cited evidence (should be a real line from the transcript): "{evidence}"

Check two things against the full transcript below:
1. Does the cited evidence actually appear in the transcript (word-for-word or a very close paraphrase)? Do not accept a fabricated or invented quote.
2. Does that evidence genuinely support the claim as stated? Do not accept a claim that overstates, misreads, or contradicts what the evidence actually says.

Return ONLY valid JSON, no markdown fences, no commentary:
{{"verified": true, "reason": "brief explanation, especially if false"}}

Full transcript:
\"\"\"
{transcript}
\"\"\"
"""

REEXTRACT_PROMPT_TEMPLATE = """A previous attempt to extract a "{field}" claim from this transcript was rejected during verification.

Previous claim: "{text}"
Previous evidence: "{evidence}"
Rejection reason: "{reason}"

Look at the transcript again and try to find a CORRECT "{field}" claim, fixing the problem above. If you genuinely cannot find valid evidence for a "{field}" claim anywhere in the transcript, say so explicitly rather than inventing one.

Return ONLY valid JSON, no markdown fences, matching exactly this shape:
{{"found": true, "text": "corrected claim or null", "evidence": "exact quote or null"}}

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


def build_verify_prompt(transcript: str, field: str, text: str, evidence: str | None) -> str:
    return VERIFY_PROMPT_TEMPLATE.format(field=field, text=text, evidence=evidence or "", transcript=transcript)


def build_reextract_prompt(transcript: str, field: str, text: str, evidence: str | None, reason: str | None) -> str:
    return REEXTRACT_PROMPT_TEMPLATE.format(
        field=field, text=text, evidence=evidence or "", reason=reason or "unspecified", transcript=transcript
    )


def _extract_json(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, re.DOTALL)
    if fenced:
        raw_text = fenced.group(1)
    return json.loads(raw_text)


def parse_verify_response(raw_text: str) -> VerifyResult:
    parsed = _extract_json(raw_text)
    return VerifyResult(verified=bool(parsed.get("verified")), reason=parsed.get("reason"))


def parse_reextract_response(raw_text: str) -> ReextractResult:
    parsed = _extract_json(raw_text)
    return ReextractResult(found=bool(parsed.get("found")), text=parsed.get("text"), evidence=parsed.get("evidence"))


def verify_claim_core(
    transcript: str,
    claim: dict,
    verify_fn: Callable[[str, str, str, str | None], VerifyResult],
    reextract_fn: Callable[[str, str, str, str | None, str | None], ReextractResult],
    max_retries: int = MAX_RETRIES,
) -> ClaimUpdate:
    """The actual bounded retry loop — pure control flow, network calls
    injected as callables so this is fully testable without a real API."""
    field = claim["field"]
    text = claim["text"]
    evidence = claim.get("evidence_line")
    retries = claim.get("retries", 0)

    while True:
        result = verify_fn(transcript, field, text, evidence)

        if result.verified:
            return ClaimUpdate(status="confirmed", text=text, evidence_line=evidence, retries=retries)

        if retries >= max_retries:
            return ClaimUpdate(
                status="partial", text=text, evidence_line=evidence, retries=retries,
                note=f"retries exhausted: {result.reason}",
            )

        reextracted = reextract_fn(transcript, field, text, evidence, result.reason)
        retries += 1

        if not reextracted.found or not reextracted.text or not reextracted.evidence:
            # No better claim exists anywhere in the transcript — further
            # retries on the SAME rejected claim would just repeat this
            # exact outcome, so stop here rather than loop pointlessly.
            return ClaimUpdate(
                status="partial", text=text, evidence_line=evidence, retries=retries,
                note="no corrected claim found on retry",
            )

        # got a corrected claim — loop back and verify THAT instead
        text = reextracted.text
        evidence = reextracted.evidence


def _call_gemini_verify(transcript: str, field: str, text: str, evidence: str | None, settings: GeminiSettings) -> VerifyResult:
    from google import genai

    client = genai.Client(api_key=settings.api_key)
    response = client.models.generate_content(
        model=settings.model, contents=build_verify_prompt(transcript, field, text, evidence)
    )
    return parse_verify_response(response.text)


def _call_gemini_reextract(
    transcript: str, field: str, text: str, evidence: str | None, reason: str | None, settings: GeminiSettings
) -> ReextractResult:
    from google import genai

    client = genai.Client(api_key=settings.api_key)
    response = client.models.generate_content(
        model=settings.model, contents=build_reextract_prompt(transcript, field, text, evidence, reason)
    )
    return parse_reextract_response(response.text)


def verify_claim(transcript: str, claim: dict, settings: GeminiSettings) -> ClaimUpdate:
    """Thin, obviously-correct wrapper around verify_claim_core with real
    Gemini calls — the actual retry logic lives in verify_claim_core and
    is what's unit-tested."""
    return verify_claim_core(
        transcript,
        claim,
        verify_fn=lambda t, f, txt, ev: _call_gemini_verify(t, f, txt, ev, settings),
        reextract_fn=lambda t, f, txt, ev, reason: _call_gemini_reextract(t, f, txt, ev, reason, settings),
    )
