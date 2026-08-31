"""
render — the payoff node. Compiles a prospect's current, already-verified
state (persona, score, open claims, latest recommendation) into the
actual one-page brief a rep opens before their next call.

Pure, deterministic Markdown assembly — ZERO API calls, same category as
score's point arithmetic and formatter.py's transcript rendering. Nothing
is decided here; everything was already decided and verified by earlier
stages. This just presents it.

The one rule that matters most, same as everywhere else in this pipeline:
a claim type with zero open claims does NOT get an empty placeholder
section — it's omitted entirely. Nothing invented to fill space.

One current brief per PROSPECT, not one per call — a rep always wants the
latest picture, so each new job overwrites the same file rather than
piling up historical versions (the claims table itself already preserves
full history; the brief is a snapshot of "right now").
"""

from __future__ import annotations

from dataclasses import dataclass

# Display order: problems and open loops first (most actionable), context
# and positives after, accountability tracking last. Matches how a rep
# actually wants to scan before a call — "what needs fixing" before
# "what's going well".
FIELD_ORDER = ["objection", "risk_signal", "open_question", "pain_point", "interest", "commitment"]

FIELD_LABELS = {
    "objection": "Objections",
    "risk_signal": "Risk Signals",
    "open_question": "Open Questions",
    "pain_point": "Pain Points",
    "interest": "Interests",
    "commitment": "Commitments",
}

STATUS_FLAG = {"confirmed": "", "partial": " \u2757"}  # partial claims flagged, confirmed ones unmarked


@dataclass
class BriefResult:
    markdown: str
    sections_included: list[str]
    sections_omitted: list[str]


def _claim_line(claim: dict) -> str:
    flag = STATUS_FLAG.get(claim.get("status"), "")
    mention_note = f" _(mentioned {claim['mention_count']}x)_" if (claim.get("mention_count") or 1) > 1 else ""
    evidence = claim.get("evidence_line")
    evidence_part = f' — _"{evidence}"_' if evidence else ""
    return f"- {claim['text']}{evidence_part}{mention_note}{flag}"


def render_brief(prospect: dict, open_claims: list[dict], recommendation: dict | None) -> BriefResult:
    by_field: dict[str, list[dict]] = {}
    for c in open_claims:
        by_field.setdefault(c["field"], []).append(c)

    name = prospect.get("name") or "Unknown prospect"
    company = prospect.get("company")
    role = prospect.get("role_title")

    lines: list[str] = [f"# {name}" + (f" — {company}" if company else "")]
    if role:
        lines.append(f"_{role}_")
    lines.append("")

    if prospect.get("persona_overview"):
        lines.append(prospect["persona_overview"])
        lines.append("")

    has_score = prospect.get("interest_score") is not None and prospect.get("risk_score") is not None
    if has_score:
        lines.append(
            f"**Interest: {prospect['interest_score']}/100** \u00b7 "
            f"**Risk: {prospect['risk_score']}/100 ({prospect.get('risk_level', 'unknown')})**"
        )
        if prospect.get("score_summary"):
            lines.append(f"> {prospect['score_summary']}")
        lines.append("")

    if recommendation:
        lines.append("## Next Call")
        if recommendation.get("recommended_opening"):
            lines.append(f"**Open with:** {recommendation['recommended_opening']}")
        if recommendation.get("next_best_action"):
            lines.append(f"**Do next:** {recommendation['next_best_action']}")
        lines.append("")

    sections_included: list[str] = []
    sections_omitted: list[str] = []

    for field in FIELD_ORDER:
        claims = by_field.get(field, [])
        if not claims:
            sections_omitted.append(field)
            continue
        sections_included.append(field)
        lines.append(f"## {FIELD_LABELS[field]}")
        for c in claims:
            lines.append(_claim_line(c))
        lines.append("")

    if not sections_included:
        lines.append("_No open items on file — nothing currently outstanding._")
        lines.append("")

    lines.append("---")
    lines.append("_\u2757 = confirmed but lower-confidence (worth a human glance) \u00b7 no mark = fully confirmed_")

    return BriefResult(markdown="\n".join(lines), sections_included=sections_included, sections_omitted=sections_omitted)
