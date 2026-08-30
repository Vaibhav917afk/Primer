"""
Central configuration for the primer backend.

This is the DEPLOYED service (Render) — no GPU, no local model weights, no
torch. Both transcription paths are hosted APIs (Deepgram + Gemini), so this
config is intentionally lightweight compared to the original local-dev setup.

WhisperXSettings is kept here ONLY because transcribe_whisperx.py imports it
at module level and that file is being left untouched as a dormant,
local-dev-only fallback (see transcribe_whisperx.py's own docstring). It is
never instantiated or called by the deployed pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# --------------------------------------------------------------------------- #
# Active (deployed) settings
# --------------------------------------------------------------------------- #

@dataclass
class DeepgramSettings:
    api_key: str | None = field(default_factory=lambda: os.getenv("DEEPGRAM_API_KEY"))
    model: str = field(default_factory=lambda: os.getenv("DEEPGRAM_MODEL") or "nova-3")


@dataclass
class GeminiSettings:
    api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL") or "gemini-3.5-flash")


@dataclass
class SupabaseSettings:
    url: str | None = field(default_factory=lambda: os.getenv("SUPABASE_URL"))
    # SERVICE ROLE key — this backend runs server-side only, never expose this
    # value to any frontend code. It bypasses row-level security by design.
    service_role_key: str | None = field(default_factory=lambda: os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    raw_bucket: str = field(default_factory=lambda: os.getenv("SUPABASE_RAW_BUCKET") or "raw-uploads")
    output_bucket: str = field(default_factory=lambda: os.getenv("SUPABASE_OUTPUT_BUCKET") or "transcripts")


@dataclass
class WebhookSettings:
    # Shared secret Supabase's Database Webhook sends as a header, so random
    # internet traffic can't trigger (paid) transcription calls on our endpoint.
    secret: str | None = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET"))


@dataclass
class CompareSettings:
    similarity_threshold: float = 0.82
    time_tolerance: float = 1.5
    arbitrate_disagreements: bool = True


DEEPGRAM = DeepgramSettings()
GEMINI = GeminiSettings()
SUPABASE = SupabaseSettings()
WEBHOOK = WebhookSettings()
COMPARE = CompareSettings()

WORK_DIR = Path("/tmp/primer_jobs")
WORK_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
TEXT_EXTENSIONS = {".txt", ".md", ".json"}


# --------------------------------------------------------------------------- #
# Dormant — kept only so transcribe_whisperx.py still imports cleanly.
# Not used by the deployed pipeline. See README for the local-dev fallback.
# --------------------------------------------------------------------------- #

def _gpu_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


HAS_GPU = _gpu_available()


@dataclass
class WhisperXSettings:
    device: str = "cuda" if HAS_GPU else "cpu"
    compute_type: str = "float16" if HAS_GPU else "int8"
    model_size: str = field(
        default_factory=lambda: os.getenv("WHISPER_MODEL_SIZE") or ("large-v3" if HAS_GPU else "small")
    )
    batch_size: int = 16 if HAS_GPU else 4
    enable_alignment: bool = HAS_GPU
    hf_token: str | None = field(default_factory=lambda: os.getenv("HF_TOKEN"))
    enable_diarization: bool = True
    language: str | None = field(default_factory=lambda: os.getenv("WHISPER_LANGUAGE") or None)
