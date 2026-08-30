"""
formatter — turn the reconciled segments into output a human can actually
read at a glance, plus a JSON form the next pipeline stage can consume.
Unchanged from the tested local version.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from compare import CompareResult

STATUS_MARK = {
    "agreed": "",
    "resolved": "\u26a0\ufe0f",
    "low_confidence": "\u2757",
    "gemini_only": "\U0001F50A",
}


def _mmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def to_markdown(result: CompareResult, source_name: str) -> str:
    lines = [
        f"# Transcript — {source_name}",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_ · "
        f"{result.agreement_count} agreed segments, {result.disagreement_count} flagged",
        "",
        "> \u2757 = kept as-is, low confidence (worth a human glance) "
        "\u00b7 \u26a0\ufe0f = auto-resolved by arbitration "
        "\u00b7 \U0001F50A = only Gemini caught this, Deepgram has nothing here "
        "\u00b7 no mark = both systems agreed",
        "",
        "---",
        "",
    ]
    current_speaker = None
    for seg in result.segments:
        mark = STATUS_MARK.get(seg.status, "")
        if seg.speaker != current_speaker:
            lines.append(f"\n**{seg.speaker}**  `[{_mmss(seg.start)}\u2013{_mmss(seg.end)}]`")
            current_speaker = seg.speaker
        else:
            lines.append(f"`[{_mmss(seg.start)}\u2013{_mmss(seg.end)}]`")
        lines.append(f"> {seg.text} {mark}".rstrip())
        lines.append("")

    if result.notes:
        lines += ["---", "", "### Notes", ""]
        lines += [f"- {n}" for n in result.notes]

    return "\n".join(lines)


def to_json(result: CompareResult, source_name: str) -> dict:
    return {
        "source": source_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agreement_count": result.agreement_count,
        "disagreement_count": result.disagreement_count,
        "gemini_only_count": result.gemini_only_count,
        "segments": [
            {
                "start": s.start, "end": s.end, "speaker": s.speaker, "text": s.text,
                "status": s.status, "similarity": s.similarity,
            }
            for s in result.segments
        ],
        "notes": result.notes,
    }


def write_outputs(result: CompareResult, source_name: str, output_dir: Path) -> tuple[Path, Path]:
    stem = Path(source_name).stem
    md_path = output_dir / f"{stem}.transcript.md"
    json_path = output_dir / f"{stem}.transcript.json"

    md_path.write_text(to_markdown(result, source_name), encoding="utf-8")
    json_path.write_text(json.dumps(to_json(result, source_name), indent=2), encoding="utf-8")
    return md_path, json_path
