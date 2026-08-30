"""
extract — reads the (possibly chunked) transcript and pulls out persona,
interests, objections, commitments, and sentiment — each one tied to the
exact line it came from. Every claim is written with status="pending",
awaiting the verify step (not built yet) to independently check it.

Design note on claim.status: the original design used a 3-state model
(confirmed/partial/omitted) decided at verify-time. At extract-time, list-
type fields (objections/interests/commitments) represent "nothing found"
simply by having zero rows — no placeholder needed. Singular fields
(persona components, overall sentiment) that come back null from the model
are skipped entirely rather than written as an explicit "omitted" row.
This is a deliberate simplification, not an oversight: it keeps the table
clean, and "no evidence, no claim" is still exactly what happens.

Also handles finding-or-creating the prospect this job belongs to, since
persona extraction naturally produces the identity info (name, company,
email) needed to do that matching.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from config import GeminiSettings
from preprocess import Chunk, chunk_transcript

FIELDS = ["interest", "objection", "commitment"]

PROMPT_TEMPLATE = """You are analyzing part of a business conversation transcript (a sales call, meeting, or similar) to build a persistent record of the other party.

Read the transcript excerpt below and extract ONLY what is actually said — never invent or infer beyond the text.

Extract:
1. persona: any of {{name, role, company, email}} that are explicitly stated or clearly identifiable. Omit any field not actually mentioned (use null).
2. interests: things the prospect expressed genuine interest in. Each needs the exact quote it came from.
3. objections: concerns, pushback, or hesitations raised. Each needs the exact quote it came from.
4. commitments: promises or next steps either party agreed to. Each needs the exact quote it came from.
5. sentiment: one of "positive", "neutral", "negative", or "mixed" — the overall tone of THIS excerpt specifically. Omit (null) if genuinely unclear.

Return ONLY valid JSON, no markdown fences, no commentary, matching exactly this shape:

{{
  "persona": {{"name": null, "role": null, "company": null, "email": null}},
  "interests": [{{"text": "...", "evidence": "exact quote"}}],
  "objections": [{{"text": "...", "evidence": "exact quote"}}],
  "commitments": [{{"text": "...", "evidence": "exact quote"}}],
  "sentiment": null
}}

Transcript excerpt:
\"\"\"
{transcript}
\"\"\"
"""


@dataclass
class ExtractedItem:
    field: str
    text: str
    evidence_line: str | None


@dataclass
class ExtractedPersona:
    name: str | None = None
    role: str | None = None
    company: str | None = None
    email: str | None = None


@dataclass
class ChunkExtraction:
    persona: ExtractedPersona
    items: list[ExtractedItem]
    sentiment: str | None


@dataclass
class ExtractionResult:
    persona: ExtractedPersona
    items: list[ExtractedItem]
    overall_sentiment: str | None
    notes: list[str] = field(default_factory=list)


def build_prompt(transcript_chunk: str) -> str:
    return PROMPT_TEMPLATE.format(transcript=transcript_chunk)


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def parse_extraction_response(raw_text: str) -> ChunkExtraction:
    """Pure parsing — separated from the network call so it's fully
    testable with a fixed sample response."""
    parsed = _extract_json(raw_text)

    persona_raw = parsed.get("persona") or {}
    persona = ExtractedPersona(
        name=persona_raw.get("name"),
        role=persona_raw.get("role"),
        company=persona_raw.get("company"),
        email=persona_raw.get("email"),
    )

    items: list[ExtractedItem] = []
    for field_name in FIELDS:
        for entry in parsed.get(f"{field_name}s", []) or []:
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            items.append(ExtractedItem(field=field_name, text=text, evidence_line=entry.get("evidence")))

    sentiment = parsed.get("sentiment")
    return ChunkExtraction(persona=persona, items=items, sentiment=sentiment)


def merge_chunk_results(chunk_results: list[ChunkExtraction]) -> ExtractionResult:
    """Pure merge logic — combines every chunk's extraction into one
    result. Persona fields: first non-null value wins per field, since a
    name mentioned once holds for the whole call. Sentiment: majority vote
    across chunks that had an opinion, "mixed" as the tiebreak."""
    persona = ExtractedPersona()
    all_items: list[ExtractedItem] = []
    sentiments: list[str] = []
    notes: list[str] = []

    for result in chunk_results:
        if not persona.name and result.persona.name:
            persona.name = result.persona.name
        if not persona.role and result.persona.role:
            persona.role = result.persona.role
        if not persona.company and result.persona.company:
            persona.company = result.persona.company
        if not persona.email and result.persona.email:
            persona.email = result.persona.email

        all_items.extend(result.items)
        if result.sentiment:
            sentiments.append(result.sentiment)

    overall_sentiment = None
    if sentiments:
        counts = {s: sentiments.count(s) for s in set(sentiments)}
        max_count = max(counts.values())
        winners = [s for s, c in counts.items() if c == max_count]
        overall_sentiment = winners[0] if len(winners) == 1 else "mixed"

    if len(chunk_results) > 1:
        notes.append(f"merged extraction across {len(chunk_results)} chunks")

    return ExtractionResult(persona=persona, items=all_items, overall_sentiment=overall_sentiment, notes=notes)


def _call_gemini_extract(transcript_chunk: str, settings: GeminiSettings) -> str:
    from google import genai

    client = genai.Client(api_key=settings.api_key)
    response = client.models.generate_content(model=settings.model, contents=build_prompt(transcript_chunk))
    return response.text


def extract_from_transcript(transcript_text: str, settings: GeminiSettings) -> ExtractionResult:
    """Top-level orchestration: chunk if needed, call Gemini per chunk,
    merge. The pure functions above (build_prompt, parse_extraction_response,
    merge_chunk_results) carry the real logic and are tested independently;
    this function is a thin, obviously-correct wrapper around them."""
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
