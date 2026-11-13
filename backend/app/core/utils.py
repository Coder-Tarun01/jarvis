"""Small shared helpers: UTC time, ISO formatting, retry/backoff, NL time parsing."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, TypeVar

T = TypeVar("T")

log = logging.getLogger("jarvis.utils")


# --------------------------------------------------------------------------- time
def utcnow() -> datetime:
    """Naive UTC 'now' — the single timestamp convention of this project."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local_naive(dt: datetime) -> datetime:
    """Treat a naive-UTC datetime as UTC and render it in the server's local zone."""
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat() + "Z"


def human_time(dt: datetime) -> str:
    return to_local_naive(dt).strftime("%A %d %B %Y at %H:%M")


# --------------------------------------------------------------------------- time parsing
_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}

_REL_1 = re.compile(r"^in\s+(\d+(?:\.\d+)?)\s*([a-z]+)$", re.I)
_REL_2 = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-z]+)\s+from\s+now$", re.I)
_REL_3 = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-z]+)$", re.I)
_CLOCK = r"(?:at\s+|@\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"


def _localise(value: datetime) -> datetime:
    """Local wall-clock datetime -> naive UTC."""
    if value.tzinfo is None:
        value = value.astimezone()  # interpret as the machine's local time
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _with_clock(base: datetime, hh: int, mm: int, ampm: str | None) -> datetime:
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hh < 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"invalid clock time {hh}:{mm}")
    return base.replace(hour=hh, minute=mm, second=0, microsecond=0)


def parse_when(value: str, now: datetime | None = None) -> datetime:
    """Parse 'in 10 minutes', 'tomorrow at 9pm', '2026-01-01T10:00' into naive UTC.

    Raises ValueError with a readable message when the input is not understood.
    """
    if value is None or not str(value).strip():
        raise ValueError("empty time expression")
    raw = str(value).strip()
    text = raw.lower()

    # 1) ISO 8601 / explicit datetimes
    try:
        return _localise(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return _localise(datetime.strptime(raw, fmt))
        except ValueError:
            continue

    now_local = to_local_naive(now) if now is not None else datetime.now()
    base = now_local

    # 2) relative: "in 5 minutes", "10 min from now", "90s"
    for pattern in (_REL_1, _REL_2, _REL_3):
        match = pattern.match(text)
        if match:
            amount = float(match.group(1))
            unit = match.group(2).rstrip(".")
            if unit not in _UNIT_SECONDS:
                raise ValueError(
                    f"unknown time unit '{unit}' (use seconds, minutes, hours or days)"
                )
            return _localise(base + timedelta(seconds=amount * _UNIT_SECONDS[unit]))

    # 3) day words
    day_offset = 0
    if "day after tomorrow" in text:
        day_offset = 2
        text = text.replace("day after tomorrow", "").strip(" ,")
    elif "tomorrow" in text:
        day_offset = 1
        text = text.replace("tomorrow", "").strip(" ,")
    else:
        text = text.replace("tonight", "").replace("today", "").strip(" ,")

    target_day = base + timedelta(days=day_offset)
    clock = re.search(_CLOCK, text)
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        ampm = clock.group(3)
        if "tonight" in raw.lower() and ampm is None and hour <= 12:
            hour += 12
        candidate = _with_clock(target_day, hour, minute, ampm)
        if day_offset == 0 and candidate <= base:
            candidate += timedelta(days=1)
        return _localise(candidate)

    if day_offset:
        return _localise(_with_clock(target_day, 9, 0, None))

    raise ValueError(
        f"could not understand the time '{value}'. Try 'in 20 minutes', "
        "'tomorrow at 9:30', 'today at 18:00' or an ISO timestamp."
    )


# --------------------------------------------------------------------------- misc
# --------------------------------------------------------------------------- names
def name_tokens(text: str) -> list[str]:
    """'Prashant  Frd' -> ['prashant', 'frd'] — words only, lowercased."""
    return [token for token in re.split(r"[^a-z0-9]+", (text or "").lower()) if token]


def _word_matches(query_token: str, candidate_word: str) -> bool:
    """One spoken word against one word of a stored name.

    Short stored words ("F", "Pr") are only accepted on an exact hit — otherwise
    'Prashant' would match 'Kameshvarao F Pr' just because it starts with 'Pr'.
    """
    if query_token == candidate_word:
        return True
    if len(candidate_word) >= 3 and query_token.startswith(candidate_word):
        return True
    return candidate_word.startswith(query_token)


def name_matches_tokens(query: str, candidate: str) -> bool:
    """True when every spoken word matches some word of the candidate, in any order."""
    wanted = name_tokens(query)
    if len(wanted) < 2:
        return False  # single-word lookups are handled by exact/prefix matching
    words = name_tokens(candidate)
    if not words:
        return False
    return all(any(_word_matches(token, word) for word in words) for token in wanted)


def truncate(text: str, limit: int = 4000) -> str:

    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"


def json_safe(value: Any) -> Any:
    """Best-effort conversion so tool handlers can return anything JSON-ish."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return str(value)


def result_to_text(value: Any) -> str:
    """Tool result -> string handed back to the model."""
    safe = json_safe(value)
    if isinstance(safe, str):
        return safe
    return json.dumps(safe, ensure_ascii=False)


async def retry_async(
    call: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    label: str = "request",
    retry_on: Iterable[type[BaseException]] = (Exception,),
    retry_if: Callable[[BaseException], bool] | None = None,
) -> T:
    """Exponential backoff with jitter. Re-raises the last error."""
    retry_types = tuple(retry_on)
    delay = base_delay
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            should_retry = retry_if(exc) if retry_if is not None else isinstance(exc, retry_types)
            if not should_retry:
                raise
            last = exc
            if attempt >= attempts:
                break
            sleep_for = min(max_delay, delay) + random.uniform(0, 0.35)
            log.warning(
                "%s failed (attempt %s/%s): %s — retrying in %.1fs",
                label, attempt, attempts, exc, sleep_for,
            )
            await asyncio.sleep(sleep_for)
            delay *= 2
    assert last is not None
    raise last
