"""
compare — the actual flaw-fixing step in the pipeline. Unchanged from the
tested local version (includes the gemini_only fix — segments Gemini caught
that the other path has no record of at all are surfaced, not dropped).

Speaker labels from each system are independently numbered, so this module
maps Deepgram's speaker labels onto Gemini's (or vice versa) using
time-overlap, before comparing any text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .config import CompareSettings, GeminiSettings
from .transcribe_whisperx import Segment


@dataclass
class FinalSegment:
    start: float
    end: float
    speaker: str
    text: str
    status: str  # "agreed" | "resolved" | "low_confidence" | "gemini_only"
    whisperx_text: str | None = None  # kept as field name for continuity — holds Path A's (Deepgram's) text
    gemini_text: str | None = None
    similarity: float | None = None


@dataclass
class CompareResult:
    segments: list[FinalSegment]
    disagreement_count: int
    agreement_count: int
    gemini_only_count: int = 0
    notes: list[str] = field(default_factory=list)


def _overlap_simple(a: Segment, b: Segment, tolerance: float) -> float:
    a_start, a_end = a.start - tolerance, a.end + tolerance
    b_start, b_end = b.start - tolerance, b.end + tolerance
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _build_speaker_map(wx_segments: list[Segment], gm_segments: list[Segment], tolerance: float) -> dict[str, str]:
    weights: dict[tuple[str, str], float] = {}
    for a in wx_segments:
        for b in gm_segments:
            ov = _overlap_simple(a, b, tolerance)
            if ov > 0:
                key = (b.speaker, a.speaker)
                weights[key] = weights.get(key, 0.0) + ov

    mapping: dict[str, str] = {}
    for gm_speaker in {b.speaker for b in gm_segments}:
        candidates = {wx: w for (gm, wx), w in weights.items() if gm == gm_speaker}
        mapping[gm_speaker] = max(candidates, key=candidates.get) if candidates else gm_speaker
    return mapping


def _best_match_idx(target: Segment, pool: list[Segment], tolerance: float) -> int | None:
    best_idx, best_ov = None, 0.0
    for i, cand in enumerate(pool):
        ov = _overlap_simple(target, cand, tolerance)
        if ov > best_ov:
            best_idx, best_ov = i, ov
    return best_idx


def _arbitrate(wx_text: str, gm_text: str, settings: GeminiSettings) -> tuple[str, str]:
    try:
        from google import genai

        client = genai.Client(api_key=settings.api_key)
        prompt = (
            "Two speech-to-text systems transcribed the same short audio "
            "segment and disagree. Pick whichever is more plausible as "
            "natural spoken English, or lightly merge them if both capture "
            "part of the truth. Reply with ONLY the corrected text, nothing else.\n\n"
            f"System A: {wx_text}\nSystem B: {gm_text}"
        )
        response = client.models.generate_content(model=settings.model, contents=prompt)
        return response.text.strip(), "arbitrated"
    except Exception as exc:  # noqa: BLE001
        return wx_text, f"arbitration failed, kept deepgram text ({exc})"


def compare_transcripts(
    wx_segments: list[Segment],
    gm_segments: list[Segment],
    compare_settings: CompareSettings,
    gemini_settings: GeminiSettings,
) -> CompareResult:
    notes: list[str] = []
    speaker_map = _build_speaker_map(wx_segments, gm_segments, compare_settings.time_tolerance)
    relabeled_gm = [
        Segment(s.start, s.end, speaker_map.get(s.speaker, s.speaker), s.text) for s in gm_segments
    ]

    final: list[FinalSegment] = []
    agreements = disagreements = 0
    matched_gm_indices: set[int] = set()

    for wx in wx_segments:
        idx = _best_match_idx(wx, relabeled_gm, compare_settings.time_tolerance)
        match = relabeled_gm[idx] if idx is not None else None
        if idx is not None:
            matched_gm_indices.add(idx)

        if match is None:
            final.append(FinalSegment(wx.start, wx.end, wx.speaker, wx.text, "low_confidence",
                                       whisperx_text=wx.text, gemini_text=None))
            disagreements += 1
            continue

        similarity = fuzz.ratio(wx.text.lower(), match.text.lower()) / 100.0
        speakers_agree = wx.speaker == match.speaker

        if similarity >= compare_settings.similarity_threshold and speakers_agree:
            final.append(FinalSegment(wx.start, wx.end, wx.speaker, wx.text, "agreed",
                                       whisperx_text=wx.text, gemini_text=match.text, similarity=similarity))
            agreements += 1
        else:
            disagreements += 1
            if compare_settings.arbitrate_disagreements and gemini_settings.api_key:
                text, reason = _arbitrate(wx.text, match.text, gemini_settings)
                notes.append(f"segment {wx.start:.1f}-{wx.end:.1f}s: {reason}")
                status = "resolved" if reason == "arbitrated" else "low_confidence"
            else:
                text, status = wx.text, "low_confidence"
            final.append(FinalSegment(wx.start, wx.end, wx.speaker, text, status,
                                       whisperx_text=wx.text, gemini_text=match.text, similarity=similarity))

    gemini_only = 0
    for i, gm in enumerate(relabeled_gm):
        if i not in matched_gm_indices:
            final.append(FinalSegment(gm.start, gm.end, gm.speaker, gm.text, "gemini_only",
                                       whisperx_text=None, gemini_text=gm.text))
            gemini_only += 1

    if gemini_only:
        notes.append(
            f"{gemini_only} segment(s) were only caught by Gemini — Deepgram has no "
            f"corresponding text at all for that time range. Worth a manual listen."
        )

    final.sort(key=lambda s: s.start)
    return CompareResult(final, disagreements, agreements, gemini_only, notes)
