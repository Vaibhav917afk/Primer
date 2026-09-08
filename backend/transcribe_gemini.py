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
    from api_keys import get_client_for_key
    from retry_utils import call_with_key_rotation

    # Upload and generation MUST use the same key — an uploaded file is
    # scoped to the project that uploaded it, so rotating keys between the
    # two steps would leave the second key holding a file reference it
    # can't actually read. Both happen inside one rotation attempt, on one
    # cached client (see api_keys.get_client_for_key for why caching
    # matters — per-call clients caused real closed-connection failures).
    def upload_and_generate(api_key: str):
        client = get_client_for_key(api_key)
        print(f"[gemini] uploading {source_path.name} for model={settings.model}")
        uploaded = _upload_file(client, source_path)
        return client.models.generate_content(model=settings.model, contents=[uploaded, PROMPT])

    response = call_with_key_rotation(upload_and_generate)

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
