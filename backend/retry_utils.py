"""
retry_utils — a small, shared retry-with-backoff wrapper for every Gemini
call in this codebase.

Only retries genuinely TRANSIENT failures: 503 UNAVAILABLE / "high
demand" / other 5xx server errors. These are Google's infrastructure
being momentarily overloaded, not a real problem with the request — a
short wait reliably clears them, which is exactly what a real production
job hit and could have recovered from automatically instead of failing
outright.

Deliberately does NOT retry 429 RESOURCE_EXHAUSTED (quota exhaustion) —
that's a per-day cap, not a per-minute one. Retrying a few seconds later
is futile and just burns more of an already-exhausted daily budget on a
request that will fail again immediately. That one needs a human to
switch keys/models, so it's left to fail fast with a clear error instead
of silently eating retry attempts for nothing.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 2.0


def is_transient(exc: Exception) -> bool:
    """Checked defensively by class name and message text rather than
    importing the SDK's specific exception types directly — keeps this
    module lightweight and avoids an import-order dependency on
    google-genai from a shared utility every other file relies on."""
    class_name = type(exc).__name__
    message = str(exc)

    if "RESOURCE_EXHAUSTED" in message or "429" in message:
        return False  # quota — never worth retrying immediately

    if class_name == "ServerError":
        return True
    if "503" in message or "UNAVAILABLE" in message or "overloaded" in message.lower():
        return True

    return False


def call_with_retry(fn: Callable[[], T], max_attempts: int = MAX_ATTEMPTS, base_delay: float = BASE_DELAY_SECONDS) -> T:
    """Runs fn(), retrying with exponential backoff ONLY on transient
    errors. Non-transient errors (quota, bad requests, anything else)
    propagate immediately on the first attempt — retrying those would
    either be futile or actively wrong."""
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not is_transient(exc) or attempt == max_attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(f"[retry] transient error on attempt {attempt}/{max_attempts}, waiting {delay}s: {exc}")
            time.sleep(delay)

    raise last_exc  # pragma: no cover — unreachable, keeps type checkers happy
