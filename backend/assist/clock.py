"""The current time in Berlin, for everything that says "today" or "tomorrow".

ASSIST_NOW (e.g. 2026-11-04T09:00, Berlin local) fixes the clock at that
moment, for demo mode and the evals: every run sees the same day and hour.
Unset: the real time.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # imported early by modules that load before agent.py's load_dotenv()

BERLIN = ZoneInfo("Europe/Berlin")


def _fixed() -> datetime | None:
    raw = os.getenv("ASSIST_NOW", "").strip()
    if not raw:
        return None
    moment = datetime.fromisoformat(raw)
    # A plain local time is Berlin time; one with an offset is converted
    return moment.replace(tzinfo=BERLIN) if moment.tzinfo is None else moment.astimezone(BERLIN)


FIXED = _fixed()


def now() -> datetime:
    """Berlin time: ASSIST_NOW if set, otherwise the real time."""
    return FIXED or datetime.now(BERLIN)
