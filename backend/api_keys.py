"""
api_keys — rotates across multiple Gemini API keys so one exhausted daily
quota doesn't stop the pipeline.

Quota on Gemini's free tier is per Google Cloud PROJECT, not per key — so
this only actually helps if each key comes from a genuinely separate
project (create additional projects under your own account, which is the
normal supported way to do this). Multiple keys from the SAME project
share one quota pool and rotating between them buys nothing.

Configured via GEMINI_API_KEYS (comma-separated) in the environment, with
GEMINI_API_KEY still honored as a single-key fallback so nothing breaks
for an existing deployment that hasn't switched over.

Behavior: keys are tried in order. When one returns a 429 (quota
exhausted), it's marked exhausted for the rest of the process and the
next key is used. Exhaustion is deliberately NOT persisted across
restarts — quotas reset daily, and a redeploy is exactly when you'd want
to give a previously-exhausted key another chance.
"""

from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_exhausted: set[str] = set()


def _load_keys() -> list[str]:
    multi = os.getenv("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in multi.split(",") if k.strip()]
    if keys:
        return keys
    single = os.getenv("GEMINI_API_KEY", "").strip()
    return [single] if single else []


def get_available_keys() -> list[str]:
    """Every configured key that hasn't hit its quota yet this process.
    Falls back to ALL keys if every one is marked exhausted — better to
    retry a possibly-reset quota than to hard-fail with nothing to try."""
    keys = _load_keys()
    with _lock:
        available = [k for k in keys if k not in _exhausted]
    return available or keys


def mark_exhausted(key: str) -> None:
    with _lock:
        _exhausted.add(key)
    print(f"[api_keys] key ...{key[-6:]} marked exhausted for this process")


def is_quota_error(exc: Exception) -> bool:
    message = str(exc)
    return "RESOURCE_EXHAUSTED" in message or "429" in message


# --------------------------------------------------------------------------- #
# Client cache
#
# One genai.Client per API key, reused for the lifetime of the process.
#
# This exists because of a real production failure: constructing a NEW
# client on every call (which the key-rotation refactor originally did)
# meant each call opened its own httpx connection pool. When an earlier
# client object was garbage-collected it closed its pool, which could
# invalidate a connection a newer client was mid-request on, producing
# "Cannot send a request, as the client has been closed."
#
# Caching per key fixes it at the root: clients are never discarded, so
# their pools are never closed underneath an in-flight request. It's also
# simply more efficient — connection pools get reused instead of rebuilt
# on every single call.
# --------------------------------------------------------------------------- #

_client_cache: dict[str, object] = {}
_client_lock = threading.Lock()


def get_client_for_key(api_key: str):
    """Returns a cached genai.Client for this key, creating it on first use.
    Thread-safe: extract.py calls this from parallel worker threads."""
    with _client_lock:
        cached = _client_cache.get(api_key)
        if cached is not None:
            return cached

        from google import genai

        client = genai.Client(api_key=api_key)
        _client_cache[api_key] = client
        return client
