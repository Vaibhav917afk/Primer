"""
score — turns a prospect's current, reconciled claim history into an
interest score and a risk score, against a FIXED, DISCLOSED rubric —
never a trained model. The lit review's own citation (Verbeke et al.,
2012) is explicit about why: there's no labeled deal-outcome data to
validate a real predictive model against, so the honest move is a
documented, auditable point formula instead of a number nobody can
explain.

The point arithmetic (compute_scores) is 100% deterministic code — ZERO
API calls. Every point is traceable to a specific rubric rule and a
specific set of claim ids; nothing here is an LLM's opinion.

The only LLM involvement is a short natural-language explanation of the
score for a human reader (verify_score checks THIS doesn't overstate what
the evidence shows) — the number itself is never something an LLM decides.

Only claims with state="open" count (resolved/superseded claims are, by
definition, no longer part of the CURRENT picture). Confirmed claims count
at full weight; partial claims (verified, but not with full confidence)
count at half weight, rounded down — lower-confidence evidence should
still matter less than fully-confirmed evidence, not be ignored entirely.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from typing import Callable

from config import GeminiSettings

# --------------------------------------------------------------------------- #
# The rubric itself — every number here is a deliberate, disclosed choice,
# not a trained weight. Change these constants to retune scoring; the
# formula shape (base + capped contributions per factor) stays the same.
# No historical outcome data exists to calibrate these against (same
# limitation the lit review already discloses for this whole approach) —
# they encode a reasonable, explainable prioritization, not a validated
# prediction.
# --------------------------------------------------------------------------- #

INTEREST_BASE = 30
INTEREST_PER_OPEN_INTEREST = 20
INTEREST_MAX_INTEREST_COUNTED = 3
INTEREST_PER_OPEN_COMMITMENT = 15
INTEREST_MAX_COMMITMENT_COUNTED = 2
INTEREST_PER_RESOLVED_OBJECTION = 10
INTEREST_MAX_RESOLVED_COUNTED = 3
INTEREST_PER_OPEN_OBJECTION_PENALTY = -10
INTEREST_MAX_OBJECTION_PENALTY_COUNTED = 3

RISK_BASE = 20
RISK_PER_OPEN_OBJECTION = 20
RISK_MAX_OBJECTION_COUNTED = 3
RISK_PER_OPEN_RISK_SIGNAL = 25
RISK_MAX_RISK_SIGNAL_COUNTED = 2
RISK_PER_STALLED_QUESTION = 10  # an open_question with mention_count > 1 — asked more than once, still unanswered
RISK_MAX_STALLED_COUNTED = 2
RISK_PER_OPEN_COMMITMENT_RELIEF = -15  # things ARE moving forward
RISK_MAX_COMMITMENT_RELIEF_COUNTED = 2

RISK_LEVEL_LOW_MAX = 33
RISK_LEVEL_MEDIUM_MAX = 66


@dataclass
class ScoreFactor:
    label: str
    points: int
    claim_ids: list[str]


@dataclass
class ScoreResult:
    interest_score: int
    risk_score: int
    risk_level: str
    interest_factors: list[ScoreFactor]
    risk_factors: list[ScoreFactor]


def _claim_weight(claim: dict) -> float:
    """Confirmed = full weight, partial = half weight, rounded down at
    the end — lower-confidence evidence counts for less, not nothing."""
    return 1.0 if claim.get("status") == "confirmed" else 0.5


def _capped_contribution(claims: list[dict], per_item: int, max_counted: int) -> tuple[int, list[str]]:
    """Sorts confirmed claims before partial ones so full-confidence
    evidence fills the cap first — a believable, disclosed tie-break rule,
    not an arbitrary one."""
    ordered = sorted(claims, key=lambda c: 0 if c.get("status") == "confirmed" else 1)
    counted = ordered[:max_counted]
    points = sum(per_item * _claim_weight(c) for c in counted)
    return int(points), [c["id"] for c in counted]


def compute_scores(open_claims: list[dict], resolved_claims: list[dict]) -> ScoreResult:
    """Pure, deterministic, zero API calls. open_claims: state='open' for
    this prospect. resolved_claims: state='resolved' for this prospect —
    only used for the "resolved objection" positive-momentum factor."""

    by_field = {}
    for c in open_claims:
        by_field.setdefault(c["field"], []).append(c)

    resolved_objections = [c for c in resolved_claims if c["field"] == "objection"]
    stalled_questions = [c for c in by_field.get("open_question", []) if (c.get("mention_count") or 1) > 1]

    interest_factors: list[ScoreFactor] = []
    interest_total = INTEREST_BASE

    pts, ids = _capped_contribution(by_field.get("interest", []), INTEREST_PER_OPEN_INTEREST, INTEREST_MAX_INTEREST_COUNTED)
    if ids:
        interest_factors.append(ScoreFactor(f"{len(ids)} open interest signal(s)", pts, ids))
        interest_total += pts

    pts, ids = _capped_contribution(by_field.get("commitment", []), INTEREST_PER_OPEN_COMMITMENT, INTEREST_MAX_COMMITMENT_COUNTED)
    if ids:
        interest_factors.append(ScoreFactor(f"{len(ids)} open commitment(s)", pts, ids))
        interest_total += pts

    pts, ids = _capped_contribution(resolved_objections, INTEREST_PER_RESOLVED_OBJECTION, INTEREST_MAX_RESOLVED_COUNTED)
    if ids:
        interest_factors.append(ScoreFactor(f"{len(ids)} previously-open objection(s) now resolved", pts, ids))
        interest_total += pts

    pts, ids = _capped_contribution(by_field.get("objection", []), INTEREST_PER_OPEN_OBJECTION_PENALTY, INTEREST_MAX_OBJECTION_PENALTY_COUNTED)
    if ids:
        interest_factors.append(ScoreFactor(f"{len(ids)} unresolved objection(s) dampening interest", pts, ids))
        interest_total += pts

    risk_factors: list[ScoreFactor] = []
    risk_total = RISK_BASE

    pts, ids = _capped_contribution(by_field.get("objection", []), RISK_PER_OPEN_OBJECTION, RISK_MAX_OBJECTION_COUNTED)
    if ids:
        risk_factors.append(ScoreFactor(f"{len(ids)} unresolved objection(s)", pts, ids))
        risk_total += pts

    pts, ids = _capped_contribution(by_field.get("risk_signal", []), RISK_PER_OPEN_RISK_SIGNAL, RISK_MAX_RISK_SIGNAL_COUNTED)
    if ids:
        risk_factors.append(ScoreFactor(f"{len(ids)} open risk signal(s)", pts, ids))
        risk_total += pts

    pts, ids = _capped_contribution(stalled_questions, RISK_PER_STALLED_QUESTION, RISK_MAX_STALLED_COUNTED)
    if ids:
        risk_factors.append(ScoreFactor(f"{len(ids)} question(s) raised more than once, still unanswered", pts, ids))
        risk_total += pts

    pts, ids = _capped_contribution(by_field.get("commitment", []), RISK_PER_OPEN_COMMITMENT_RELIEF, RISK_MAX_COMMITMENT_RELIEF_COUNTED)
    if ids:
        risk_factors.append(ScoreFactor(f"{len(ids)} open commitment(s) showing forward motion", pts, ids))
        risk_total += pts

    interest_score = max(0, min(100, interest_total))
    risk_score = max(0, min(100, risk_total))

    if risk_score <= RISK_LEVEL_LOW_MAX:
        risk_level = "low"
    elif risk_score <= RISK_LEVEL_MEDIUM_MAX:
        risk_level = "medium"
    else:
        risk_level = "high"

    return ScoreResult(
        interest_score=interest_score, risk_score=risk_score, risk_level=risk_level,
        interest_factors=interest_factors, risk_factors=risk_factors,
    )


# --------------------------------------------------------------------------- #
# The narrative — the ONLY part of this file that calls an LLM. Explains
# the already-computed score in plain English, grounded only in the
# factors actually used to compute it.
# --------------------------------------------------------------------------- #

NARRATIVE_PROMPT_TEMPLATE = """A sales prospect has been scored using a fixed rubric. Write ONE short sentence (max 30 words) explaining the risk score in plain English, grounded ONLY in the factors listed below — do not invent or infer anything beyond them.

Interest score: {interest_score}/100
Risk score: {risk_score}/100 ({risk_level})

Interest factors:
{interest_factors}

Risk factors:
{risk_factors}

Return ONLY valid JSON, no markdown fences:
{{"summary": "one grounded sentence here"}}
"""

VERIFY_NARRATIVE_PROMPT_TEMPLATE = """Check this one-sentence summary of a prospect's score against the actual factors it should be grounded in. Does it accurately reflect them, without overstating, inventing, or omitting something that changes the picture?

Summary: "{summary}"

Interest factors: {interest_factors}
Risk factors: {risk_factors}

Return ONLY valid JSON, no markdown fences:
{{"accurate": true, "reason": "brief explanation if false"}}
"""


@dataclass
class NarrativeResult:
    summary: str
    status: str  # "confirmed" | "partial"
    retries: int


def _format_factors(factors: list[ScoreFactor]) -> str:
    if not factors:
        return "(none)"
    return "\n".join(f"- {f.label}: {f.points:+d} points" for f in factors)


def build_narrative_prompt(result: ScoreResult) -> str:
    return NARRATIVE_PROMPT_TEMPLATE.format(
        interest_score=result.interest_score, risk_score=result.risk_score, risk_level=result.risk_level,
        interest_factors=_format_factors(result.interest_factors), risk_factors=_format_factors(result.risk_factors),
    )


def build_verify_narrative_prompt(summary: str, result: ScoreResult) -> str:
    return VERIFY_NARRATIVE_PROMPT_TEMPLATE.format(
        summary=summary, interest_factors=_format_factors(result.interest_factors), risk_factors=_format_factors(result.risk_factors)
    )


def _extract_json(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, re.DOTALL)
    if fenced:
        raw_text = fenced.group(1)
    return json.loads(raw_text)


def parse_narrative_response(raw_text: str) -> str:
    return str(_extract_json(raw_text).get("summary", "")).strip()


def parse_verify_narrative_response(raw_text: str) -> tuple[bool, str | None]:
    parsed = _extract_json(raw_text)
    return bool(parsed.get("accurate")), parsed.get("reason")


def generate_and_verify_narrative_core(
    result: ScoreResult,
    generate_fn: Callable[[ScoreResult], str],
    verify_fn: Callable[[str, ScoreResult], tuple[bool, str | None]],
    max_retries: int = 2,
) -> NarrativeResult:
    """Bounded retry, same pattern as verify.py's claim loop: generate,
    check, regenerate if needed, never loop forever."""
    retries = 0
    summary = generate_fn(result)

    while True:
        accurate, reason = verify_fn(summary, result)
        if accurate:
            return NarrativeResult(summary=summary, status="confirmed", retries=retries)
        if retries >= max_retries:
            return NarrativeResult(summary=summary, status="partial", retries=retries)
        retries += 1
        summary = generate_fn(result)


def _call_gemini_narrative(result: ScoreResult, settings: GeminiSettings) -> str:
    from google import genai

    from retry_utils import call_with_retry

    client = genai.Client(api_key=settings.api_key)
    response = call_with_retry(
        lambda: client.models.generate_content(model=settings.model, contents=build_narrative_prompt(result))
    )
    return parse_narrative_response(response.text)


def _call_gemini_verify_narrative(summary: str, result: ScoreResult, settings: GeminiSettings) -> tuple[bool, str | None]:
    from google import genai

    from retry_utils import call_with_retry

    client = genai.Client(api_key=settings.api_key)
    response = call_with_retry(
        lambda: client.models.generate_content(model=settings.model, contents=build_verify_narrative_prompt(summary, result))
    )
    return parse_verify_narrative_response(response.text)


def score_prospect(open_claims: list[dict], resolved_claims: list[dict], settings: GeminiSettings) -> tuple[ScoreResult, NarrativeResult]:
    result = compute_scores(open_claims, resolved_claims)
    narrative = generate_and_verify_narrative_core(
        result,
        generate_fn=lambda r: _call_gemini_narrative(r, settings),
        verify_fn=lambda s, r: _call_gemini_verify_narrative(s, r, settings),
    )
    return result, narrative
