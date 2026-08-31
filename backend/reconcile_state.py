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
                   longer applies. Silence is NEVER treated as resolution
                   — a topic simply not coming up again in one call is not
                   evidence it went away, only an explicit contradiction is.
  - "superseded"  this exact row was a duplicate of an existing claim,
                   merged into it. Kept in the table (never deleted) so
                   the full history of how a belief evolved is never lost.

One combined Gemini call per job handles both matching AND resolution
detection together — after the quota lesson from verify.py, this pipeline
defaults to batching, not one-call-per-decision.

Matching only ever happens WITHIN the same claim field (an objection can
never match against an interest) — different field types shouldn't share
a matching pool. If a prospect has no existing open claims at all (their
very first call), reconciliation short-circuits with zero API calls —
there's nothing to reconcile against.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from config import GeminiSettings

RECONCILE_PROMPT_TEMPLATE = """You are updating a persistent profile for a business prospect, based on a NEW conversation, given claims already on file from PREVIOUS conversations with the same prospect.

EXISTING claims on file (grouped by type, each has an id):
{existing_block}

NEW claims from today's conversation (numbered):
{new_block}

Do two things:

1. For each NEW claim, check if it describes the SAME underlying thing as an EXISTING claim of the SAME type (just reworded, or elaborated — not a different topic). If so, give that existing claim's id. If it's genuinely a new topic, say so.

2. For each EXISTING claim that was NOT matched by any new claim above, check whether anything in today's NEW claims provides CLEAR, EXPLICIT evidence that it is no longer true / has been resolved / no longer applies. Do NOT mark something resolved just because it wasn't mentioned again this call — silence is not evidence. Only mark it resolved if there is a real, explicit statement contradicting or resolving it.

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
    notes: list[str]


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


def reconcile_claims_core(
    existing: list[ExistingClaim],
    new: list[NewClaim],
    reconcile_fn: Callable[[list[ExistingClaim], list[NewClaim]], ReconcileOutcome],
) -> ReconcileOutcome:
    """Pure orchestration. Matching only happens within the same field —
    existing/new are pre-filtered to a single field by the caller, OR this
    function groups by field itself and reconciles each group separately,
    merging the results. We do the latter here so callers can just pass
    everything at once."""
    if not existing:
        # First call ever for this prospect (or first claim of this type)
        # — nothing to reconcile against, zero API calls needed.
        return ReconcileOutcome(
            matches=[ClaimMatch(new_claim_id=c.id, matches_existing_id=None) for c in new],
            resolved_existing_ids=[],
            notes=["no existing claims — skipped reconciliation call entirely"],
        )

    fields_present = {c.field for c in existing} | {c.field for c in new}
    all_matches: list[ClaimMatch] = []
    all_resolved: list[str] = []
    all_notes: list[str] = []

    for field in fields_present:
        existing_for_field = [c for c in existing if c.field == field]
        new_for_field = [c for c in new if c.field == field]

        if not new_for_field:
            continue  # nothing new of this type this round — existing claims of this type just stay as-is

        if not existing_for_field:
            all_matches.extend(ClaimMatch(new_claim_id=c.id, matches_existing_id=None) for c in new_for_field)
            continue

        outcome = reconcile_fn(existing_for_field, new_for_field)
        all_matches.extend(outcome.matches)
        all_resolved.extend(outcome.resolved_existing_ids)
        all_notes.extend(outcome.notes)

    return ReconcileOutcome(matches=all_matches, resolved_existing_ids=all_resolved, notes=all_notes)


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
