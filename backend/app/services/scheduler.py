"""Background reminder scheduler.

Polling (not cron, not APScheduler) keeps this dependency-free and predictable
for a single-user local app: every REMINDER_POLL_SECONDS we look for due rows,
mark them fired, and push them to every connected browser.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..core.config import Settings, get_settings
from ..core.db import SessionLocal
from ..core.logging import get_logger
from ..core.models import Reminder
from ..core.utils import human_time, iso, utcnow

log = get_logger("scheduler")


async def fire_due_reminders() -> int:
    """Mark due reminders as fired and push them. Returns how many fired."""
    from .hub import hub  # local import keeps this module import-safe

    db = SessionLocal()
    fired = 0
    try:
        due = list(
            db.scalars(
                select(Reminder)
                .where(Reminder.fired.is_(False), Reminder.due_at <= utcnow())
                .order_by(Reminder.due_at.asc())
                .limit(20)
            ).all()
        )
        for reminder in due:
            reminder.fired = True
            reminder.fired_at = utcnow()
            db.commit()
            fired += 1
            log.info("firing %s #%s: %s", reminder.kind, reminder.id, reminder.text)
            await hub.broadcast(
                {
                    "type": "reminder",
                    "id": reminder.id,
                    "text": reminder.text,
                    "kind": reminder.kind,
                    "due_at": iso(reminder.due_at),
                    "due_human": human_time(reminder.due_at),
                }
            )
    finally:
        db.close()
    return fired


async def reminder_loop(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    interval = max(1.0, float(settings.reminder_poll_seconds))
    log.info("reminder scheduler started (every %.0fs)", interval)
    while True:
        try:
            await fire_due_reminders()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("reminder sweep failed")
        await asyncio.sleep(interval)
