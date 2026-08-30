"""
extract — reads the (possibly chunked) transcript and pulls out, per
distinct speaker: identity (name/role/company/persona overview) and
whether they're the sales rep or the prospect — plus a full set of
claim types tied to both a transcript quote and which speaker said it,
named entities mentioned, and lightweight topic labels.

Claim fields, and why each exists:
  - interest      genuine positive interest in something specific
  - objection     pushback or concern directed AT us/our product/pricing
  - pain_point    a problem in their current situation, not necessarily
                   about us — context that makes the pitch land better
  - commitment    an EXPLICIT agreement/confirmation to do something —
                   requires a real yes, not just a request or proposal
  - open_question a question or request raised with NO clear agreement
                   attached in this excerpt — this is the fix for a real
                   bug: "can you send a proposal by Friday?" was getting
                   misclassified as a commitment just because it mentioned
                   a next step, when nobody had actually said yes to it
  - risk_signal   anything suggesting the deal could stall — needing
                   another stakeholder's approval, a vague timeline,
                   evaluating a competitor. This directly feeds the future
                   score step, which needs real evidence to justify a risk
                   number rather than inventing one.

interest/objection/pain_point/risk_signal are about assessing the PROSPECT
specifically, so main.py filters these to the identified prospect's
speaker_label. commitment/open_question matter regardless of who raised
them (an open loop is an open loop no matter who left it open), so those
are kept unfiltered.

Design note on claim.status: the original design used a 3-state model
(confirmed/partial/omitted) decided at verify-time. At extract-time, list-
type fields represent "nothing found" simply by having zero rows — no
placeholder needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from config import GeminiSettings
from preprocess import Chunk, chunk_transcript

ITEM_FIELDS = ["interest", "objection", "pain_point", "commitment", "open_question", "risk_signal"]
PROSPECT_ONLY_FIELDS = {"interest", "objection", "pain_point", "risk_signal"}
ROLE_VALUES = {"rep", "prospect", "other", "unknown"}

PROMPT_TEMPLATE = """You are analyzing part of a business conversation transcript (a sales call, meeting, or similar). Each line is labeled with who is speaking — SPEAKER_00, SPEAKER_01, etc. The same label always refers to the same person throughout this excerpt.

Read the transcript excerpt below and extract ONLY what is actually said — never invent or infer beyond the text.

Extract:

1. participants: every distinct speaker_label that appears. For each, identify {{name, role_in_call, role_title, company, email, persona_overview}}:
   - role_in_call must be exactly one of "rep" (represents the company doing the selling/pitching), "prospect" (the customer/lead being sold to), "other", or "unknown".
   - persona_overview: ONLY for the prospect — a single sentence describing who they are and how they communicate (e.g. "Ops-focused decision maker, direct and data-driven, sensitive to rollout timelines"), based only on what's actually shown in this excerpt. Omit (null) if there isn't enough to say anything real.
   - Omit any field not actually stated (use null) — do not guess a name, company, or email that isn't said.

2. interests: things the PROSPECT expressed genuine positive interest in.
3. objections: concerns or pushback directed AT us, our product, or our pricing.
4. pain_points: a problem in the prospect's CURRENT situation, even if not directly about us (e.g. "our current process is manual and slow").
5. commitments: an EXPLICIT agreement or confirmation to do something. This requires a clear yes/confirmation from whoever is responsible for it. A question, request, or proposal ALONE is NOT a commitment — if nobody actually agreed to it in this excerpt, it belongs under open_questions instead.
6. open_questions: a question or requested next step raised in this excerpt that does NOT have a clear agreement attached within this excerpt. Example: someone asks "can you send a proposal by Friday" and nobody confirms yes — that is an open_question, never a commitment.
7. risk_signals: anything suggesting this deal could stall or fail — needing another stakeholder's approval, a vague or distant timeline, evaluating a competitor, budget uncertainty. Do NOT restate a concern already captured as an objection — a risk_signal should reveal something an objection alone doesn't (e.g. not just "pricing is a concern" again, but specifically that budget approval requires someone else's sign-off, or that a decision is being delayed for an unstated reason).

Every item in 2-7 needs the exact quote it came from and which speaker_label said it.

8. entities: other named things mentioned in passing — competitor products, other companies, integrations, tools. Each needs a short label, a type ("company"|"product"|"other"), and the exact quote.
9. topics: 1-4 short topic labels (2-4 words each) describing what this excerpt covers.
10. sentiment: one of "positive", "neutral", "negative", or "mixed" — the PROSPECT's tone specifically in this excerpt. Omit (null) if unclear or no prospect speech is present.

Return ONLY valid JSON, no markdown fences, no commentary, matching exactly this shape:

{{
  "participants": [
    {{"speaker_label": "SPEAKER_00", "name": null, "role_in_call": "unknown", "role_title": null, "company": null, "email": null, "persona_overview": null}}
  ],
  "interests": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_01"}}],
  "objections": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_01"}}],
  "pain_points": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_01"}}],
  "commitments": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_00"}}],
  "open_questions": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_01"}}],
  "risk_signals": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_01"}}],
  "entities": [{{"text": "...", "type": "company", "evidence": "exact quote"}}],
  "topics": ["..."],
  "sentiment": null
}}

Transcript excerpt (each line labeled by speaker):
\"\"\"
{transcript}
\"\"\"
"""


@dataclass
class ExtractedItem:
    field: str
    text: str
    evidence_line: str | None
    speaker_label: str | None = None


@dataclass
class Participant:
    speaker_label: str | None
    name: str | None = None
    role_in_call: str = "unknown"
    role_title: str | None = None
    company: str | None = None
    email: str | None = None
    persona_overview: str | None = None


@dataclass
class ExtractedEntity:
    text: str
    type: str
    evidence_line: str | None


@dataclass
class ChunkExtraction:
    participants: list[Participant]
    items: list[ExtractedItem]
    entities: list[ExtractedEntity]
    topics: list[str]
    sentiment: str | None


@dataclass
class ExtractionResult:
    participants: list[Participant]
    items: list[ExtractedItem]
    entities: list[ExtractedEntity]
    topics: list[str]
    overall_sentiment: str | None
    notes: list[str] = field(default_factory=list)

    def prospect(self) -> Participant | None:
        for p in self.participants:
            if p.role_in_call == "prospect":
                return p
        return None


def build_prompt(transcript_chunk: str) -> str:
    return PROMPT_TEMPLATE.format(transcript=transcript_chunk)


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _field_to_key(field_name: str) -> str:
    """interest -> interests, pain_point -> pain_points, etc."""
    return f"{field_name}s"


def parse_extraction_response(raw_text: str) -> ChunkExtraction:
    parsed = _extract_json(raw_text)

    participants = []
    for p in parsed.get("participants", []) or []:
        role = p.get("role_in_call") or "unknown"
        if role not in ROLE_VALUES:
            role = "unknown"
        participants.append(
            Participant(
                speaker_label=p.get("speaker_label"),
                name=p.get("name"),
                role_in_call=role,
                role_title=p.get("role_title"),
                company=p.get("company"),
                email=p.get("email"),
                persona_overview=p.get("persona_overview"),
            )
        )

    items: list[ExtractedItem] = []
    for field_name in ITEM_FIELDS:
        for entry in parsed.get(_field_to_key(field_name), []) or []:
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            items.append(
                ExtractedItem(
                    field=field_name, text=text,
                    evidence_line=entry.get("evidence"),
                    speaker_label=entry.get("speaker_label"),
                )
            )

    entities = [
        ExtractedEntity(text=e.get("text", ""), type=e.get("type", "other"), evidence_line=e.get("evidence"))
        for e in parsed.get("entities", []) or []
        if e.get("text")
    ]

    topics = [t for t in (parsed.get("topics") or []) if t]
    sentiment = parsed.get("sentiment")

    return ChunkExtraction(participants=participants, items=items, entities=entities, topics=topics, sentiment=sentiment)


def merge_chunk_results(chunk_results: list[ChunkExtraction]) -> ExtractionResult:
    participants_by_label: dict[str, Participant] = {}
    all_items: list[ExtractedItem] = []
    all_entities: list[ExtractedEntity] = []
    all_topics: list[str] = []
    sentiments: list[str] = []
    notes: list[str] = []

    for result in chunk_results:
        for p in result.participants:
            key = p.speaker_label or f"unlabeled-{len(participants_by_label)}"
            if key not in participants_by_label:
                participants_by_label[key] = p
            else:
                existing = participants_by_label[key]
                existing.name = existing.name or p.name
                existing.role_title = existing.role_title or p.role_title
                existing.company = existing.company or p.company
                existing.email = existing.email or p.email
                existing.persona_overview = existing.persona_overview or p.persona_overview
                if existing.role_in_call == "unknown" and p.role_in_call != "unknown":
                    existing.role_in_call = p.role_in_call

        all_items.extend(result.items)
        all_entities.extend(result.entities)
        all_topics.extend(result.topics)
        if result.sentiment:
            sentiments.append(result.sentiment)

    overall_sentiment = None
    if sentiments:
        counts = {s: sentiments.count(s) for s in set(sentiments)}
        max_count = max(counts.values())
        winners = [s for s, c in counts.items() if c == max_count]
        overall_sentiment = winners[0] if len(winners) == 1 else "mixed"

    seen_topics = set()
    deduped_topics = []
    for t in all_topics:
        key = t.strip().lower()
        if key and key not in seen_topics:
            seen_topics.add(key)
            deduped_topics.append(t)

    if len(chunk_results) > 1:
        notes.append(f"merged extraction across {len(chunk_results)} chunks")

    return ExtractionResult(
        participants=list(participants_by_label.values()),
        items=all_items,
        entities=all_entities,
        topics=deduped_topics,
        overall_sentiment=overall_sentiment,
        notes=notes,
    )


def _call_gemini_extract(transcript_chunk: str, settings: GeminiSettings) -> str:
    from google import genai

    client = genai.Client(api_key=settings.api_key)
    response = client.models.generate_content(model=settings.model, contents=build_prompt(transcript_chunk))
    return response.text


def extract_from_transcript(transcript_text: str, settings: GeminiSettings) -> ExtractionResult:
    if not settings.api_key:
        raise RuntimeError("GEMINI_API_KEY is not set — check .env / Render environment")

    chunks: list[Chunk] = chunk_transcript(transcript_text)
    chunk_results: list[ChunkExtraction] = []

    for i, chunk in enumerate(chunks):
        raw = _call_gemini_extract(chunk.text, settings)
        try:
            chunk_results.append(parse_extraction_response(raw))
        except (json.JSONDecodeError, AttributeError) as exc:
            raise RuntimeError(f"chunk {i}: Gemini didn't return parseable JSON: {raw[:300]}") from exc

    return merge_chunk_results(chunk_results)
