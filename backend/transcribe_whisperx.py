"""
transcribe_whisperx — DORMANT in the deployed backend.

This file is left exactly as it was when tested locally. It is NOT part of
the deployed Render pipeline (Deepgram replaces it there — see
transcribe_deepgram.py) because torch + pyannote routinely need several GB
of RAM to load, and Render's free tier gives 512MB. Deploying with this
active would crash on startup, not just run slowly.

Kept in the repo as a documented, optional path for local, offline testing
on a machine with more RAM (or a GPU) — e.g. if you want to compare
Deepgram's output against a self-hosted WhisperX run for validation. To use
it locally: `pip install whisperx` (not in the deployed requirements.txt)
and call transcribe_with_whisperx() directly instead of transcribe_deepgram().

Also the source of the shared Segment / TranscriptResult dataclasses that
compare.py and transcribe_gemini.py import — importing THIS file does not
require whisperx to be installed, since the actual `import whisperx` only
happens lazily inside functions that are never called by the deployed path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import WhisperXSettings


@dataclass
class Segment:
    start: float
    end: float
    speaker: str
    text: str


@dataclass
class TranscriptResult:
    source: str
    segments: list[Segment]
    language: str | None
    degraded: bool
    notes: list[str]


def _try_import_whisperx():
    try:
        import whisperx  # noqa: F401

        return whisperx
    except ImportError:
        return None


def transcribe_with_whisperx(audio_path: Path, settings: WhisperXSettings) -> TranscriptResult:
    whisperx = _try_import_whisperx()
    notes: list[str] = []

    if whisperx is not None:
        return _run_full_whisperx(whisperx, audio_path, settings, notes)

    notes.append(
        "whisperx not installed — degraded to faster-whisper only "
        "(no diarization, no forced alignment). Run: pip install whisperx"
    )
    return _run_faster_whisper_fallback(audio_path, settings, notes)


def _run_full_whisperx(whisperx, audio_path: Path, settings: WhisperXSettings, notes: list[str]) -> TranscriptResult:
    print(f"[whisperx] device={settings.device} compute={settings.compute_type} model={settings.model_size}")

    model = whisperx.load_model(
        settings.model_size,
        device=settings.device,
        compute_type=settings.compute_type,
        language=settings.language,
    )
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=settings.batch_size)
    language = result.get("language")

    if settings.enable_alignment:
        try:
            align_model, meta = whisperx.load_align_model(language_code=language, device=settings.device)
            result = whisperx.align(result["segments"], align_model, meta, audio, settings.device)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"forced alignment skipped: {exc}")
    else:
        notes.append("forced alignment skipped (disabled on CPU by default — see config.py)")

    if settings.enable_diarization:
        if not settings.hf_token:
            notes.append(
                "diarization skipped — no HF_TOKEN set. Get one free at "
                "huggingface.co/settings/tokens and accept the pyannote license pages, "
                "then set HF_TOKEN in .env"
            )
        else:
            try:
                try:
                    diarize_model = whisperx.diarize.DiarizationPipeline(
                        token=settings.hf_token, device=settings.device
                    )
                except TypeError:
                    diarize_model = whisperx.diarize.DiarizationPipeline(
                        use_auth_token=settings.hf_token, device=settings.device
                    )
                diarize_segments = diarize_model(str(audio_path))
                result = whisperx.assign_word_speakers(diarize_segments, result)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"diarization failed, continuing without speaker labels: {exc}")

    segments = [
        Segment(
            start=s["start"], end=s["end"],
            speaker=s.get("speaker", "SPEAKER_00"),
            text=s["text"].strip(),
        )
        for s in result.get("segments", [])
    ]
    degraded = any("skipped" in n or "failed" in n for n in notes)
    return TranscriptResult("whisperx", segments, language, degraded, notes)


def _run_faster_whisper_fallback(audio_path: Path, settings: WhisperXSettings, notes: list[str]) -> TranscriptResult:
    from faster_whisper import WhisperModel

    print(f"[faster-whisper fallback] device={settings.device} compute={settings.compute_type} model={settings.model_size}")
    model = WhisperModel(settings.model_size, device=settings.device, compute_type=settings.compute_type)
    raw_segments, info = model.transcribe(
        str(audio_path),
        language=settings.language,
        vad_filter=True,
    )
    segments = [
        Segment(start=s.start, end=s.end, speaker="SPEAKER_00", text=s.text.strip())
        for s in raw_segments
    ]
    return TranscriptResult("whisperx", segments, info.language, True, notes)
