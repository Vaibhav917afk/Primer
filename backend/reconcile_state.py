"""
reconcile_state — the actual belief-tracking logic: when a new call comes
in for a prospect we've already talked to, does a claim get correctly
matched against one already on file (and updated, not duplicated), or
recognized as genuinely new? This is the specific problem this whole
project exists to solve.

Every claim carries a lifecycle state, separate from verify's confidence
status:
  - "open"       currently true, as far as we know
  - "resolved"    was true, explicit evidence in a LATER call shows it no
                   longer applies. Silence is NEVER treated as resolution.
  - "superseded"  this exact row was a duplicate of an existing claim,
                   merged into it. Kept in the table (never deleted) so
                   the full history of how a belief evolved is never lost.

One combined Gemini call per job handles matching AND resolution together
across ALL claim types at once — NOT grouped per field. This matters: an
earlier version of this file grouped everything by field before checking
resolution, which meant an existing "objection" could only be resolved by
a NEW claim that also happened to be type "objection" — but in practice,
resolution routinely comes through as a DIFFERENT field entirely (e.g. a
new "interest" claim confirming budget approval is exactly what resolves
an old pricing "objection"). Proven wrong by a real test, not a hunch —
see the fix below.

Matching itself still only ever happens WITHIN the same claim field (an
objection can never match against an interest) — that constraint is
correct and stays. It's enforced two ways: the prompt is told explicitly,
AND the code defensively rejects any cross-type match the model returns
anyway, rather than trusting it blindly.

If a prospect has no existing open claims at all, reconciliation
short-circuits with zero API calls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from typing import Callable

from config import GeminiSettings

RECONCILE_PROMPT_TEMPLATE = """You are updating a persistent profile for a business prospect, based on a NEW conversation, given claims already on file from PREVIOUS conversations with the same prospect.

EXISTING claims on file (each has an id and a type):
{existing_block}

NEW claims from today's conversation (numbered, each has a type):
{new_block}

Do two things:

1. MATCHING — for each NEW claim, check if it describes the SAME underlying thing as an EXISTING claim of the EXACT SAME type (an objection can only match another objection, an interest can only match another interest — never match across different types). If so, give that existing claim's id. If it's a new topic, or there's no existing claim of that same type to compare against, say it's new.

2. RESOLUTION — for each EXISTING claim NOT matched above, check whether ANY of the NEW claims — of ANY type, not just the same type — provide CLEAR, EXPLICIT evidence that it is no longer true or has been resolved. A new "interest" or "commitment" claim can absolutely resolve an old "objection" (for example: a new claim confirming budget was approved resolves an old objection that pricing was too high). Do NOT mark something resolved just because it wasn't mentioned again this call — silence is never evidence. Only mark it resolved if there is a real, explicit statement resolving or contradicting it.

Return ONLY valid JSON, no markdown fences, no commentary, matching exactly this shape:

{{
  "new_claim_matches": [
    {{"new_claim_index": 1, "matches_existing_id": "existing-id-or-null", "is_new_topic": true}}
  ],
  "resolved_existing_ids": ["existing-id", "existing-id"]
}}
"""


@dataclass
class ExistingClaim:
    id: str
    field: str
    text: str


@dataclass
class NewClaim:
    id: str
    field: str
    text: str


@dataclass
class ClaimMatch:
    new_claim_id: str
    matches_existing_id: str | None  # None = genuinely new


@dataclass
class ReconcileOutcome:
    matches: list[ClaimMatch]
    resolved_existing_ids: list[str]
    notes: list[str] = dc_field(default_factory=list)


def _format_existing_block(existing: list[ExistingClaim]) -> str:
    if not existing:
        return "(none)"
    return "\n".join(f'[id: {c.id}] type: {c.field} | text: "{c.text}"' for c in existing)


def _format_new_block(new: list[NewClaim]) -> str:
    return "\n".join(f'[{i + 1}] type: {c.field} | text: "{c.text}"' for i, c in enumerate(new))


def build_reconcile_prompt(existing: list[ExistingClaim], new: list[NewClaim]) -> str:
    return RECONCILE_PROMPT_TEMPLATE.format(
        existing_block=_format_existing_block(existing), new_block=_format_new_block(new)
    )


def _extract_json(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, re.DOTALL)
    if fenced:
        raw_text = fenced.group(1)
    return json.loads(raw_text)


def parse_reconcile_response(raw_text: str, new_claims: list[NewClaim]) -> ReconcileOutcome:
    parsed = _extract_json(raw_text)
    notes: list[str] = []

    raw_matches = parsed.get("new_claim_matches", []) or []
    match_by_index = {m.get("new_claim_index"): m for m in raw_matches}

    matches: list[ClaimMatch] = []
    for i, claim in enumerate(new_claims):
        m = match_by_index.get(i + 1)
        if m is None:
            notes.append(f"no match decision returned for new claim {i + 1} — treated as new")
            matches.append(ClaimMatch(new_claim_id=claim.id, matches_existing_id=None))
        else:
            matches.append(ClaimMatch(new_claim_id=claim.id, matches_existing_id=m.get("matches_existing_id")))

    resolved_ids = [str(x) for x in (parsed.get("resolved_existing_ids") or [])]
    return ReconcileOutcome(matches=matches, resolved_existing_ids=resolved_ids, notes=notes)


def _reject_cross_type_matches(
    outcome: ReconcileOutcome, existing: list[ExistingClaim], new: list[NewClaim]
) -> ReconcileOutcome:
    """Defensive safety net: even though the prompt explicitly forbids
    cross-type matches, never blindly trust the model on this — a mixed-up
    match here would merge an objection into an interest, corrupting the
    prospect's record. Downgrade any such match to 'new' instead."""
    existing_by_id = {c.id: c for c in existing}
    new_by_id = {c.id: c for c in new}
    notes = list(outcome.notes)
    safe_matches = []

    for m in outcome.matches:
        if m.matches_existing_id:
            existing_claim = existing_by_id.get(m.matches_existing_id)
            new_claim = new_by_id.get(m.new_claim_id)
            if existing_claim and new_claim and existing_claim.field != new_claim.field:
                notes.append(
                    f"rejected cross-type match: new claim {m.new_claim_id} ({new_claim.field}) "
                    f"vs existing {m.matches_existing_id} ({existing_claim.field}) — treated as new instead"
                )
                safe_matches.append(ClaimMatch(new_claim_id=m.new_claim_id, matches_existing_id=None))
                continue
        safe_matches.append(m)

    return ReconcileOutcome(matches=safe_matches, resolved_existing_ids=outcome.resolved_existing_ids, notes=notes)


def reconcile_claims_core(
    existing: list[ExistingClaim],
    new: list[NewClaim],
    reconcile_fn: Callable[[list[ExistingClaim], list[NewClaim]], ReconcileOutcome],
) -> ReconcileOutcome:
    """Pure orchestration. ONE call covers everything at once — matching
    AND resolution, across all claim types together — specifically so
    resolution evidence can come from a different field than what it
    resolves (see this module's docstring for why that matters)."""
    if not existing:
        return ReconcileOutcome(
            matches=[ClaimMatch(new_claim_id=c.id, matches_existing_id=None) for c in new],
            resolved_existing_ids=[],
            notes=["no existing claims — skipped reconciliation call entirely"],
        )

    if not new:
        return ReconcileOutcome(matches=[], resolved_existing_ids=[], notes=["no new claims this round"])

    outcome = reconcile_fn(existing, new)
    return _reject_cross_type_matches(outcome, existing, new)


def _call_gemini_reconcile(existing: list[ExistingClaim], new: list[NewClaim], settings: GeminiSettings) -> ReconcileOutcome:
    from google import genai

    client = genai.Client(api_key=settings.api_key)
    response = client.models.generate_content(
        model=settings.model, contents=build_reconcile_prompt(existing, new)
    )
    return parse_reconcile_response(response.text, new)


def reconcile_claims(existing: list[ExistingClaim], new: list[NewClaim], settings: GeminiSettings) -> ReconcileOutcome:
    return reconcile_claims_core(
        existing, new,
        reconcile_fn=lambda e, n: _call_gemini_reconcile(e, n, settings),
    )
