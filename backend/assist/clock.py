"""Where and when the user is: their timezone, the current time there, and their home city.

ASSIST_TIMEZONE (an IANA name such as Asia/Kolkata or America/New_York) is the
timezone for "today", "tomorrow" and every calendar time. Empty: this computer's
timezone. Demo mode keeps Europe/Berlin, the timezone the demo data is built around.

ASSIST_NOW (e.g. 2026-11-04T09:00, local time in that timezone) fixes the clock at
that moment, for demo mode and the evals: every run sees the same day and hour.
Unset: the real time.

HOME_CITY is the city for weather when none is named (and for "start my day").
Empty: Assist Voice asks; demo mode uses Albstadt, like the demo data.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # imported early by modules that load before agent.py's load_dotenv()

_TRUE = {"1", "true", "yes", "on"}
_DEMO = any(os.getenv(name, "").strip().lower() in _TRUE for name in ("DEMO_MODE", "PUBLIC_DEMO"))
DEMO_TZ = "Europe/Berlin"
DEMO_CITY = "Albstadt"


def _zone_name() -> str:
    name = os.getenv("ASSIST_TIMEZONE", "").strip()
    if name:
        return name
    if _DEMO:
        return DEMO_TZ
    try:
        from tzlocal import get_localzone_name
        return get_localzone_name() or DEMO_TZ
    except Exception:  # an unusual system setup: fall back rather than fail at startup
        return DEMO_TZ


TZ_NAME = _zone_name()
TZ = ZoneInfo(TZ_NAME)  # raises at startup on a typo in ASSIST_TIMEZONE, which is what we want
HOME_CITY = os.getenv("HOME_CITY", "").strip() or (DEMO_CITY if _DEMO else "")


def _fixed() -> datetime | None:
    raw = os.getenv("ASSIST_NOW", "").strip()
    if not raw:
        return None
    moment = datetime.fromisoformat(raw)
    # A plain time is local time in TZ; one with an offset is converted
    return moment.replace(tzinfo=TZ) if moment.tzinfo is None else moment.astimezone(TZ)


FIXED = _fixed()


def now() -> datetime:
    """The user's local time: ASSIST_NOW if set, otherwise the real time."""
    return FIXED or datetime.now(TZ)
