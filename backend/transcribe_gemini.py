"""
transcribe_gemini — Path B of the dual-transcription design.

Unchanged from the version already tested locally. Independently
transcribes and diarizes the SAME source file, without ever seeing
Deepgram's output. For video, Gemini gets the raw video (not just extracted
audio) — it can use who's visibly on screen and talking as a second
diarization signal.

Needs GEMINI_API_KEY in .env — get a free one at aistudio.google.com/apikey.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from config import GeminiSettings
from transcribe_whisperx import Segment

PROMPT = """You are transcribing a business conversation (sales call, meeting, or similar).

Listen to the full audio/video and produce a diarized transcript.

Rules:
- Identify distinct speakers and label them SPEAKER_00, SPEAKER_01, etc., in
  order of first appearance. Use the SAME label for the same speaker every
  time they talk, even if they speak multiple times.
- Give each speaker turn as one segment with an approximate start/end time
  in seconds (numbers, not "mm:ss" strings).
- Transcribe what was actually said. Do not summarize, do not paraphrase,
  do not invent words you didn't hear. If a stretch is inaudible, write
  "[inaudible]" rather than guessing.
- If this is a video, use who is visibly speaking on screen to help decide
  speaker identity when voices are similar or overlapping.

Return ONLY valid JSON, no markdown code fences, no commentary, matching
exactly this shape:

{
  "language": "en",
  "segments": [
    {"start": 0.0, "end": 4.2, "speaker": "SPEAKER_00", "text": "..."},
    {"start": 4.2, "end": 9.8, "speaker": "SPEAKER_01", "text": "..."}
  ]
}
"""


@dataclass
class GeminiTranscriptResult:
    source: str
    segments: list[Segment]
    language: str | None
    raw_response: str


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _upload_file(client, source_path: Path):
    try:
        return client.files.upload(file=str(source_path))
    except TypeError:
        return client.files.upload(path=str(source_path))


def transcribe_with_gemini(source_path: Path, settings: GeminiSettings) -> GeminiTranscriptResult:
    if not settings.api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at "
            "https://aistudio.google.com/apikey and put it in .env"
        )

    from google import genai

    from retry_utils import call_with_retry

    client = genai.Client(api_key=settings.api_key)

    print(f"[gemini] uploading {source_path.name} for model={settings.model}")
    uploaded = _upload_file(client, source_path)

    response = call_with_retry(
        lambda: client.models.generate_content(model=settings.model, contents=[uploaded, PROMPT])
    )

    raw_text = response.text
    try:
        parsed = _extract_json(raw_text)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError(
            f"Gemini didn't return parseable JSON. Raw response:\n{raw_text[:500]}"
        ) from exc

    segments = [
        Segment(
            start=float(s["start"]), end=float(s["end"]),
            speaker=s.get("speaker", "SPEAKER_00"),
            text=str(s["text"]).strip(),
        )
        for s in parsed.get("segments", [])
    ]
    return GeminiTranscriptResult("gemini", segments, parsed.get("language"), raw_text)
