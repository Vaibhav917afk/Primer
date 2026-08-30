"""
ingest — figure out what kind of file landed, and get a clean audio track
ready for both transcription paths. Unchanged from the tested local version.
Operates on a local path — main.py downloads from Supabase Storage first.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from config import AUDIO_EXTENSIONS, TEXT_EXTENSIONS, VIDEO_EXTENSIONS

ArtifactType = str


class UnsupportedFileType(Exception):
    pass


@dataclass
class IngestResult:
    artifact_type: ArtifactType
    original_path: Path
    audio_path: Path | None
    raw_text: str | None


def detect_artifact_type(path: Path) -> ArtifactType:
    ext = path.suffix.lower()
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in TEXT_EXTENSIONS:
        return "text"
    raise UnsupportedFileType(
        f"'{ext}' isn't a recognized audio, video, or text extension. "
        f"Add it to config.py if it should be supported."
    )


def extract_audio(src_path: Path, out_dir: Path) -> Path:
    out_path = out_dir / f"{src_path.stem}.norm.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(src_path),
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {src_path.name}:\n{result.stderr[-800:]}")
    return out_path


def ingest(path: str | Path, work_dir: Path) -> IngestResult:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")

    artifact_type = detect_artifact_type(path)
    print(f"[ingest] {path.name} -> {artifact_type}")

    if artifact_type == "text":
        raw_text = path.read_text(encoding="utf-8", errors="replace")
        return IngestResult(artifact_type, path, None, raw_text)

    audio_path = extract_audio(path, work_dir)
    return IngestResult(artifact_type, path, audio_path, None)
