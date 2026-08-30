"""
extract — reads the (possibly chunked) transcript and pulls out, per
distinct speaker: identity (name/role/company/email) and whether they're
the sales rep or the prospect — plus interests, objections, and
commitments each tied to both a transcript quote AND which speaker said
it, a handful of named entities mentioned (companies/products/competitors),
and lightweight topic labels for the excerpt.

This requires the transcript text to carry speaker labels (SPEAKER_00: ...
per line) — passing in undifferentiated text makes correct rep-vs-prospect
identification and per-item speaker attribution impossible, which was a
real bug in an earlier version of this pipeline (main.py was flattening
segments into one block of text with no speaker labels at all before
handing it to extract).

Design note on claim.status: the original design used a 3-state model
(confirmed/partial/omitted) decided at verify-time. At extract-time, list-
type fields (objections/interests/commitments) represent "nothing found"
simply by having zero rows — no placeholder needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from config import GeminiSettings
from preprocess import Chunk, chunk_transcript

ITEM_FIELDS = ["interest", "objection", "commitment"]
ROLE_VALUES = {"rep", "prospect", "other", "unknown"}

PROMPT_TEMPLATE = """You are analyzing part of a business conversation transcript (a sales call, meeting, or similar). Each line is labeled with who is speaking — SPEAKER_00, SPEAKER_01, etc. The same label always refers to the same person throughout this excerpt.

Read the transcript excerpt below and extract ONLY what is actually said — never invent or infer beyond the text.

Extract:
1. participants: every distinct speaker_label that appears. For each, identify {{name, role_in_call, role_title, company, email}}:
   - role_in_call must be exactly one of "rep" (represents the company doing the selling/pitching), "prospect" (the customer/lead being sold to), "other" (a third party, e.g. another attendee who is neither), or "unknown" (can't be determined from this excerpt).
   - Omit any field not actually stated (use null) — do not guess a name or company that isn't said.
2. interests: things the PROSPECT expressed genuine interest in. Each needs the exact quote and which speaker_label said it.
3. objections: concerns, pushback, or hesitations raised (usually by the prospect, but attribute to whoever actually said it). Each needs the exact quote and speaker_label.
4. commitments: promises or next steps either party agreed to. Each needs the exact quote and speaker_label.
5. entities: other named things mentioned in passing — competitor products, other companies, integrations, tools. Each needs a short label, a type ("company"|"product"|"other"), and the exact quote.
6. topics: 1-4 short topic labels (2-4 words each) describing what this excerpt covers, e.g. "pricing", "onboarding timeline", "integration requirements".
7. sentiment: one of "positive", "neutral", "negative", or "mixed" — the PROSPECT's tone specifically (not the rep's) in this excerpt. Omit (null) if unclear or no prospect speech is present.

Return ONLY valid JSON, no markdown fences, no commentary, matching exactly this shape:

{{
  "participants": [
    {{"speaker_label": "SPEAKER_00", "name": null, "role_in_call": "unknown", "role_title": null, "company": null, "email": null}}
  ],
  "interests": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_01"}}],
  "objections": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_01"}}],
  "commitments": [{{"text": "...", "evidence": "exact quote", "speaker_label": "SPEAKER_00"}}],
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
        """The primary prospect for this conversation, if one was
        identifiable. If multiple speakers were marked "prospect", the
        first one found wins — multi-prospect calls are a known
        simplification, not yet fully supported."""
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
            )
        )

    items: list[ExtractedItem] = []
    for field_name in ITEM_FIELDS:
        for entry in parsed.get(f"{field_name}s", []) or []:
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
    """Merges every chunk's extraction into one result.

    Participants: merged by speaker_label — the same speaker across chunks
    should be one entry, not duplicated. Fields fill in first-non-null; a
    role_in_call of "unknown" gets upgraded if a later chunk determines it
    more specifically (a person might not be identifiable as rep/prospect
    until later in the call)."""
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

    # dedupe topics case-insensitively, preserve first-seen order
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
    """transcript_text MUST have speaker labels per line (e.g. "SPEAKER_00:
    ...") — see main.py's transcript assembly. Without them, participant
    identification and per-item speaker attribution degrade to guessing."""
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
