"""
retry_utils — shared resilience layer for every Gemini call in this
codebase: transient-error retry with backoff, AND multi-key rotation on
quota exhaustion.

Two distinct failure modes, deliberately handled differently:

  - TRANSIENT (503 / "high demand" / 5xx): Google's infrastructure being
    momentarily overloaded. A short backoff reliably clears these — this
    has already saved real production runs, confirmed in live logs.

  - QUOTA (429 RESOURCE_EXHAUSTED): a per-day cap. Retrying the same key
    seconds later is futile. Instead, that key is marked exhausted for
    the rest of the process and the call is immediately retried with the
    NEXT available key. Only when every key is exhausted does it fail.

call_with_key_rotation() is the one to use for anything that takes an API
key. call_with_retry() remains for callers that don't (kept so existing
non-Gemini uses don't break).
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from api_keys import get_available_keys, is_quota_error, mark_exhausted

T = TypeVar("T")

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 2.0


def is_transient(exc: Exception) -> bool:
    class_name = type(exc).__name__
    message = str(exc)

    if is_quota_error(exc):
        return False  # quota — handled by key rotation, never by waiting

    if class_name == "ServerError":
        return True
    if "503" in message or "UNAVAILABLE" in message or "overloaded" in message.lower():
        return True

    return False


def call_with_retry(fn: Callable[[], T], max_attempts: int = MAX_ATTEMPTS, base_delay: float = BASE_DELAY_SECONDS) -> T:
    """Retries ONLY transient errors, with exponential backoff. Anything
    else (including quota) propagates immediately."""
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not is_transient(exc) or attempt == max_attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(f"[retry] transient error on attempt {attempt}/{max_attempts}, waiting {delay}s: {exc}")
            time.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


def call_with_key_rotation(fn: Callable[[str], T], max_attempts: int = MAX_ATTEMPTS) -> T:
    """Calls fn(api_key), rotating to the next key on quota exhaustion and
    retrying transient errors per-key. Raises if every key is exhausted."""
    keys = get_available_keys()
    if not keys:
        raise RuntimeError("No Gemini API key configured — set GEMINI_API_KEY or GEMINI_API_KEYS")

    last_exc: Exception | None = None

    for key in keys:
        try:
            return call_with_retry(lambda: fn(key), max_attempts=max_attempts)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if is_quota_error(exc):
                mark_exhausted(key)
                continue  # try the next key immediately
            raise  # anything non-quota is a real error, don't mask it by rotating

    raise last_exc if last_exc else RuntimeError("all keys exhausted")
