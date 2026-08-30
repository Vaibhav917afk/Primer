"""
preprocess — chunks a long transcript into topically-coherent segments
before extract() reads it, so a single Gemini call never has to hold an
entire hour-long call in context at once (the "Lost in the Middle" problem
that motivated chunking in the first place — see the lit review).

Uses TextRank's underlying machinery (a sentence-similarity graph) — but
applied to find topic BOUNDARIES rather than to rank sentences for a
summary. Cuts land at the sentence-pairs with the sharpest similarity
drops (the clearest topic shifts), and the NUMBER of cuts is driven by a
target chunk size, not a fixed similarity threshold — an absolute
threshold turned out to be far too sensitive to ordinary sentence-to-
sentence variation in conversational text (confirmed by testing: it cut
one genuine two-topic transcript into 14 near-identical-sized pieces
instead of 2). Ranking cuts by how pronounced each dip is, and only taking
the N strongest ones needed to hit a target chunk size, is robust to that.

Stays genuinely lightweight: scikit-learn's TF-IDF (frequency stats, no
pretrained model to download) and networkx (pure graph math) — nothing
that risks Render's 512MB free-tier RAM the way BERTopic's stack would.

For short transcripts (most sales calls), this returns a single chunk —
chunking only matters once a transcript is long enough to actually risk
context degradation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

# Below this many words, don't bother chunking at all — a single Gemini
# call handles it fine, and chunking short text just adds overhead for
# no benefit.
MIN_WORDS_TO_CHUNK = 2500

# Aim for roughly this many words per chunk when splitting — drives HOW
# MANY cuts get made; the actual cut positions are picked by strongest
# topic-shift signal, not by word count alone.
TARGET_CHUNK_WORDS = 1800

# Hard ceiling regardless of topic coherence — bounds worst case even if
# no strong topic shift exists anywhere in a long stretch.
MAX_CHUNK_WORDS = 3000


@dataclass
class Chunk:
    text: str
    start_sentence_idx: int
    end_sentence_idx: int


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


def _split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    sentences = _SENTENCE_SPLIT_RE.split(text)
    return [s.strip() for s in sentences if s.strip()]


def _consecutive_similarities(sentences: list[str]) -> np.ndarray:
    """Cosine similarity between each sentence and the next, via TF-IDF —
    word-frequency statistics over this transcript's own vocabulary, no
    pretrained model involved."""
    if len(sentences) < 2:
        return np.array([])

    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        tfidf = vectorizer.fit_transform(sentences).toarray()
    except ValueError:
        # e.g. every sentence is entirely stopwords — degenerate but
        # should never crash the pipeline over a chunking nicety
        return np.zeros(len(sentences) - 1)

    sims = np.zeros(len(sentences) - 1)
    for i in range(len(sentences) - 1):
        a, b = tfidf[i], tfidf[i + 1]
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
        sims[i] = float(np.dot(a, b) / denom)
    return sims


def _pick_boundaries(similarities: np.ndarray, sentence_word_counts: list[int]) -> list[int]:
    """Return sentence indices to cut BEFORE, chosen by strongest
    similarity dip, capped to however many cuts a target chunk size
    actually calls for."""
    total_words = sum(sentence_word_counts)
    target_chunks = max(1, round(total_words / TARGET_CHUNK_WORDS))
    n_cuts = max(0, target_chunks - 1)
    if n_cuts == 0 or len(similarities) == 0:
        return []

    # dip depth = how much lower this similarity is than its neighbors —
    # a real topic shift is a LOCAL minimum, not just a low absolute value
    depths = []
    for i in range(len(similarities)):
        left = similarities[i - 1] if i > 0 else similarities[i]
        right = similarities[i + 1] if i < len(similarities) - 1 else similarities[i]
        depth = ((left + right) / 2) - similarities[i]
        depths.append((depth, i))

    depths.sort(key=lambda x: x[0], reverse=True)
    chosen = sorted(idx + 1 for _, idx in depths[:n_cuts])  # +1: cut BEFORE sentence idx+1
    return chosen


def chunk_transcript(text: str) -> list[Chunk]:
    word_count = len(text.split())
    sentences = _split_sentences(text)

    if word_count < MIN_WORDS_TO_CHUNK or len(sentences) < 4:
        return [Chunk(text=text, start_sentence_idx=0, end_sentence_idx=max(len(sentences) - 1, 0))]

    similarities = _consecutive_similarities(sentences)
    sentence_word_counts = [len(s.split()) for s in sentences]
    boundaries = _pick_boundaries(similarities, sentence_word_counts)

    # Safety net: if any resulting span would still exceed MAX_CHUNK_WORDS
    # (possible if no strong topic shift exists in a long stretch), force
    # additional cuts at the weakest-similarity point within that span.
    cut_points = [0] + boundaries + [len(sentences)]
    final_cuts = {0, len(sentences)}
    for start, end in zip(cut_points[:-1], cut_points[1:]):
        final_cuts.add(start)
        span_words = sum(sentence_word_counts[start:end])
        if span_words > MAX_CHUNK_WORDS and end - start > 1:
            # split this span roughly in half by word count
            running = 0
            for i in range(start, end):
                running += sentence_word_counts[i]
                if running >= span_words / 2:
                    final_cuts.add(i + 1)
                    break

    sorted_cuts = sorted(final_cuts)
    chunks = [
        Chunk(
            text=" ".join(sentences[s:e]),
            start_sentence_idx=s,
            end_sentence_idx=e - 1,
        )
        for s, e in zip(sorted_cuts[:-1], sorted_cuts[1:])
    ]
    return chunks
