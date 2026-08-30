"""
transcribe_deepgram — Path A of the dual-transcription design, deployed version.

Replaces self-hosted WhisperX. Deepgram Nova-3 transcribes AND diarizes in a
single hosted API call — no local model weights, no GPU, no torch. This is
what makes the pipeline light enough to run on Render's free tier.

Deepgram's pre-recorded API returns word-level speaker labels, not
turn-level segments — this module's real job is grouping consecutive
same-speaker words into segments matching the same Segment shape Gemini's
path and compare.py already expect, so nothing downstream had to change.

Needs DEEPGRAM_API_KEY in .env — get a free one (with $200 trial credit,
no credit card) at console.deepgram.com/signup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import DeepgramSettings
from transcribe_whisperx import Segment


@dataclass
class DeepgramTranscriptResult:
    source: str  # "deepgram"
    segments: list[Segment]
    language: str | None
    notes: list[str]


def _get(obj, name: str, default=None):
    """Deepgram's SDK response can behave like an object (attribute access)
    or like a dict, depending on SDK version — handle both defensively
    rather than betting on one, given how often these APIs shift."""
    if obj is None:
        return default
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _words_to_segments(words: list) -> list[Segment]:
    """Group consecutive same-speaker words into turn-level segments."""
    segments: list[Segment] = []
    current_speaker = None
    current_words: list[str] = []
    current_start = None
    current_end = None

    for w in words:
        speaker = _get(w, "speaker")
        speaker_label = f"SPEAKER_{int(speaker):02d}" if speaker is not None else "SPEAKER_00"
        word_text = _get(w, "punctuated_word") or _get(w, "word") or ""
        start = _get(w, "start", 0.0)
        end = _get(w, "end", 0.0)

        if speaker_label != current_speaker:
            if current_speaker is not None:
                segments.append(Segment(current_start, current_end, current_speaker, " ".join(current_words)))
            current_speaker = speaker_label
            current_words = [word_text]
            current_start = start
            current_end = end
        else:
            current_words.append(word_text)
            current_end = end

    if current_speaker is not None:
        segments.append(Segment(current_start, current_end, current_speaker, " ".join(current_words)))

    return segments


def _call_deepgram(client, audio_bytes: bytes, settings: DeepgramSettings):
    """Try the current (v1.media) SDK shape first, fall back to the older
    (listen.rest.v("1")) shape if the SDK installed is an older major
    version — same defensive pattern used for the Gemini upload call."""
    try:
        return client.listen.v1.media.transcribe_file(
            request=audio_bytes,
            model=settings.model,
            diarize=True,
            punctuate=True,
            smart_format=True,
        )
    except (AttributeError, TypeError):
        from deepgram import PrerecordedOptions

        options = PrerecordedOptions(model=settings.model, diarize=True, punctuate=True, smart_format=True)
        return client.listen.rest.v("1").transcribe_file({"buffer": audio_bytes}, options)


def transcribe_with_deepgram(audio_path: Path, settings: DeepgramSettings) -> DeepgramTranscriptResult:
    if not settings.api_key:
        raise RuntimeError(
            "DEEPGRAM_API_KEY is not set. Get a free key (no credit card) at "
            "https://console.deepgram.com/signup and put it in .env"
        )

    from deepgram import DeepgramClient  # imported lazily, keeps startup fast

    client = DeepgramClient(api_key=settings.api_key)
    notes: list[str] = []

    print(f"[deepgram] transcribing {audio_path.name} with model={settings.model}")
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    response = _call_deepgram(client, audio_bytes, settings)

    results = _get(response, "results")
    channels = _get(results, "channels", [])
    if not channels:
        notes.append("deepgram returned no channels — empty or unsupported audio?")
        return DeepgramTranscriptResult("deepgram", [], None, notes)

    alternatives = _get(channels[0], "alternatives", [])
    if not alternatives:
        notes.append("deepgram returned no transcription alternatives")
        return DeepgramTranscriptResult("deepgram", [], None, notes)

    words = _get(alternatives[0], "words", [])
    if not words:
        # Some short/silent clips have a transcript but no word-level detail —
        # fall back to one whole-file segment rather than losing the text.
        transcript = _get(alternatives[0], "transcript", "")
        notes.append("no word-level detail from deepgram — returned as one unsegmented block")
        segments = [Segment(0.0, 0.0, "SPEAKER_00", transcript)] if transcript else []
    else:
        segments = _words_to_segments(words)

    language = _get(response, "metadata") and _get(_get(response, "metadata"), "detected_language")
    return DeepgramTranscriptResult("deepgram", segments, language, notes)
