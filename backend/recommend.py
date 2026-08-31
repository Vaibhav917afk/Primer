"""
recommend — turns the prospect's current, verified profile (open claims +
score) into a concrete next step for the rep: how to open the next
conversation, specific talking points, what to avoid, and the single most
important thing to do next.

Deliberately has NO separate verify stage, unlike extract/verify and
score/verify_score — by this point every claim and the score itself have
already been independently verified. recommend is synthesis over already-
trustworthy information, not new fact-generation.

Still grounded, not free-form: the prompt is given ONLY the actual open
claims and told to cite which ones informed the recommendation. The code
then defensively drops any cited claim id that doesn't actually exist in
the real claim list — a cheap, deterministic check, not a second LLM
call, so a hallucinated evidence pointer can't silently slip through.

If a prospect has NO open claims at all, this skips the LLM call entirely
and returns a sensible default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from config import GeminiSettings

RECOMMEND_PROMPT_TEMPLATE = """Based on this prospect's current profile, decide what the sales rep should do next. Ground your answer ONLY in the evidence below — never invent anything not actually listed.

Persona: {persona_overview}
Interest score: {interest_score}/100
Risk score: {risk_score}/100 ({risk_level})
Score summary: {score_summary}

Open claims on file (each has an id):
{claims_block}

Produce:
1. recommended_opening: a natural, specific way to open the NEXT conversation with this prospect (1-2 sentences).
2. next_best_action: the single most important concrete thing the rep should do before or during that call (1 sentence).
3. talking_points: 2-4 short, specific things worth actively raising or reinforcing in the next call.
4. avoid: 1-3 short things the rep should NOT do or bring up (e.g. don't re-raise a resolved objection, don't rush a hesitant buyer).
5. grounding_claim_ids: which of the claim ids above most directly informed this recommendation.

Return ONLY valid JSON, no markdown fences, no commentary:
{{"recommended_opening": "...", "next_best_action": "...", "talking_points": ["...", "..."], "avoid": ["...", "..."], "grounding_claim_ids": ["id1", "id2"]}}
"""

DEFAULT_NO_CLAIMS_OPENING = "No open items on file for this prospect — a simple check-in maintains the relationship."
DEFAULT_NO_CLAIMS_ACTION = "Schedule a light touch-base call; nothing urgent is currently outstanding."


@dataclass
class Recommendation:
    recommended_opening: str
    next_best_action: str
    grounding_claim_ids: list[str]
    talking_points: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)


def _format_claims_block(claims: list[dict]) -> str:
    if not claims:
        return "(none)"
    return "\n".join(f'[id: {c["id"]}] type: {c["field"]} | text: "{c["text"]}"' for c in claims)


def build_recommend_prompt(prospect: dict, open_claims: list[dict]) -> str:
    return RECOMMEND_PROMPT_TEMPLATE.format(
        persona_overview=prospect.get("persona_overview") or "(not enough information yet)",
        interest_score=prospect.get("interest_score", "n/a"),
        risk_score=prospect.get("risk_score", "n/a"),
        risk_level=prospect.get("risk_level", "unknown"),
        score_summary=prospect.get("score_summary") or "(no score summary yet)",
        claims_block=_format_claims_block(open_claims),
    )


def _extract_json(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, re.DOTALL)
    if fenced:
        raw_text = fenced.group(1)
    return json.loads(raw_text)


def parse_recommend_response(raw_text: str, open_claims: list[dict]) -> Recommendation:
    parsed = _extract_json(raw_text)
    valid_ids = {c["id"] for c in open_claims}
    cited = [cid for cid in (parsed.get("grounding_claim_ids") or []) if cid in valid_ids]
    return Recommendation(
        recommended_opening=str(parsed.get("recommended_opening", "")).strip(),
        next_best_action=str(parsed.get("next_best_action", "")).strip(),
        talking_points=[str(t).strip() for t in (parsed.get("talking_points") or []) if str(t).strip()],
        avoid=[str(a).strip() for a in (parsed.get("avoid") or []) if str(a).strip()],
        grounding_claim_ids=cited,
    )


def _call_gemini_recommend(prospect: dict, open_claims: list[dict], settings: GeminiSettings) -> Recommendation:
    from google import genai

    from retry_utils import call_with_retry

    client = genai.Client(api_key=settings.api_key)
    response = call_with_retry(
        lambda: client.models.generate_content(model=settings.model, contents=build_recommend_prompt(prospect, open_claims))
    )
    return parse_recommend_response(response.text, open_claims)


def recommend_next_action(prospect: dict, open_claims: list[dict], settings: GeminiSettings) -> Recommendation:
    if not open_claims:
        return Recommendation(
            recommended_opening=DEFAULT_NO_CLAIMS_OPENING,
            next_best_action=DEFAULT_NO_CLAIMS_ACTION,
            grounding_claim_ids=[],
            talking_points=[],
            avoid=[],
        )
    return _call_gemini_recommend(prospect, open_claims, settings)
