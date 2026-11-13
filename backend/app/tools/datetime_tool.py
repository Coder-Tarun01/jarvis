"""Current date/time — the model is not allowed to guess this."""

from __future__ import annotations

import time
from datetime import datetime

from ..core.utils import human_time, iso, to_local_naive, utcnow
from .base import Tool, ToolContext


def get_datetime(ctx: ToolContext) -> dict:
    now = utcnow()
    local = to_local_naive(now)
    return {
        "human": human_time(now),
        "local_iso": local.replace(microsecond=0).isoformat(),
        "local_date": local.strftime("%Y-%m-%d"),
        "weekday": local.strftime("%A"),
        "utc_iso": iso(now),
        "timezone": str(datetime.now().astimezone().tzinfo),
        "unix": int(time.time()),
    }


TOOLS = [
    Tool(
        name="get_datetime",
        description=(
            "Get the current local date and time, weekday and timezone. "
            "Always call this instead of assuming today's date"
        ),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_datetime,
    ),
]
