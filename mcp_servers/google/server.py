"""Google MCP server: the user's primary Google Calendar.

Sign-in is a one-time step: `uv run python scripts/google_auth.py`.
This server only loads and refreshes that token; it never opens a browser.
"""
import functools
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "secrets" / "gcp-oauth.keys.json"
TOKEN_PATH = ROOT / "secrets" / "google-token.json"

# Every Google API Assist uses. Add Gmail here later, then re-run the login script.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

TZ_NAME = "Europe/Berlin"
TZ = ZoneInfo(TZ_NAME)
CALENDAR = "primary"
MAX_RESULTS = 25
LOGIN_HINT = "Run `uv run python scripts/google_auth.py` to sign in to Google."
TIME_FORMAT_HINT = "Use local Berlin time without offset, e.g. 2026-10-29T12:00"

mcp = FastMCP("google")


class AuthError(Exception):
    pass


def _calendar():
    """Calendar API client from the saved token, refreshed if it has expired."""
    if not TOKEN_PATH.exists():
        raise AuthError(f"Google is not connected yet. {LOGIN_HINT}")
    try:
        # No scopes argument: keep the ones the token was actually granted
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    except ValueError:
        raise AuthError(f"The Google token file is invalid. {LOGIN_HINT}")
    if not creds.has_scopes(SCOPES):
        raise AuthError(f"The Google token is missing permissions. {LOGIN_HINT}")
    if not creds.valid:
        if not creds.refresh_token:
            raise AuthError(f"The Google token has expired. {LOGIN_HINT}")
        try:
            creds.refresh(Request())
        except RefreshError:
            raise AuthError(f"The Google token was revoked or has expired. {LOGIN_HINT}")
        TOKEN_PATH.write_text(creds.to_json())  # save the new access token
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


STALE_ID_ERROR = (
    "Event not found or already deleted. "
    "Use list_events or search_events to find the current id."
)


class StaleEventError(Exception):
    pass


def _live_event(calendar, event_id: str) -> dict:
    """Fetch an event, refusing ones that are already deleted.

    Google still returns deleted events for a while, with status "cancelled",
    so an old id from chat history can look valid. Restored events get a new id.
    """
    event = calendar.events().get(calendarId=CALENDAR, eventId=event_id).execute()
    if event.get("status") == "cancelled":
        raise StaleEventError
    return event


def google_tool(fn):
    """Turn sign-in and API failures into {"error": ...} results the model can read."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AuthError as e:
            return {"error": str(e)}
        except StaleEventError:
            return {"error": "Event already deleted. Use list_events or search_events to find the current id."}
        except HttpError as e:
            if e.resp.status in (404, 410):
                return {"error": STALE_ID_ERROR}
            return {"error": f"Google Calendar error {e.resp.status}: {e.reason}"}
        except ValueError as e:
            return {"error": f"Invalid date or time: {e}"}
    return wrapper


def _local(t: dict) -> str | None:
    """Calendar time -> the format create_event accepts: '2026-10-29' or Berlin '2026-10-29T12:00'.

    Results use the same format as inputs, so Gemini never sees an offset to
    copy, and undo can pass a deleted event's times straight to create_event.
    """
    if "dateTime" in t:
        return datetime.fromisoformat(t["dateTime"]).astimezone(TZ).strftime("%Y-%m-%dT%H:%M")
    return t.get("date")


def _compact(event: dict) -> dict:
    """Only the fields Assist needs, so results stay short."""
    start, end = event.get("start", {}), event.get("end", {})
    out = {
        "id": event["id"],
        "title": event.get("summary", "(no title)"),
        "start": _local(start),
        "end": _local(end),
        "description": event.get("description", ""),
    }
    if event.get("location"):
        out["location"] = event["location"]
    return out


def _parse(value: str) -> date | datetime:
    """'2026-10-29' -> date (all-day); '2026-10-29T12:00' -> datetime in Berlin.

    Rejects offsets and 'Z': Gemini's own UTC conversions were wrong
    ('12 pm' became 13:00Z), so the server does all time zone handling.
    """
    if "T" not in value:
        return date.fromisoformat(value)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        raise ValueError(TIME_FORMAT_HINT)
    return dt.replace(tzinfo=TZ)


def _when(moment: date | datetime) -> dict:
    """Parsed time -> Calendar API time."""
    if isinstance(moment, datetime):  # check first: datetime is a subclass of date
        return {"dateTime": moment.isoformat(), "timeZone": TZ_NAME}
    return {"date": moment.isoformat()}


def _events(days_ahead: int, query: str | None = None) -> dict:
    """Events from midnight today up to `days_ahead` days later, soonest first."""
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    params = {
        "calendarId": CALENDAR,
        "timeMin": today.isoformat(),
        "timeMax": (today + timedelta(days=days_ahead)).isoformat(),
        "singleEvents": True,  # expand recurring events into single dates
        "orderBy": "startTime",
        "maxResults": MAX_RESULTS,
        "timeZone": TZ_NAME,
    }
    if query:
        params["q"] = query
    items = _calendar().events().list(**params).execute().get("items", [])
    return {"events": [_compact(e) for e in items]}


@mcp.tool()
@google_tool
def list_events(days_ahead: int = 1) -> dict:
    """List events on the user's Google Calendar, starting today.
    Use for 'what's on my calendar', 'am I free tomorrow', 'my schedule this week'.
    `days_ahead` is 1-90: 1 = today, 2 = today and tomorrow, 7 = this week."""
    return _events(max(1, min(days_ahead, 90)))


@mcp.tool()
@google_tool
def search_events(query: str, days_ahead: int = 30) -> dict:
    """Find upcoming calendar events by text (title, description, location).
    Use when the user names an event, e.g. 'when is my dentist appointment'.
    Searches from today up to `days_ahead` days (1-365)."""
    return _events(max(1, min(days_ahead, 365)), query)


@mcp.tool()
@google_tool
def get_event(event_id: str) -> dict:
    """Get one calendar event by its id (from list_events or search_events)."""
    return _compact(_live_event(_calendar(), event_id))


@mcp.tool()
@google_tool
def create_event(title: str, start: str, end: str, description: str = "") -> dict:
    """Create an event on the user's Google Calendar.
    Times are local Berlin time WITHOUT offset or Z, e.g. '2026-10-29T12:00'.
    Never convert to UTC. A plain date like '2026-10-29' makes an all-day event;
    for all-day events `end` is the day AFTER the last day."""
    start_at, end_at = _parse(start), _parse(end)
    if isinstance(start_at, datetime) != isinstance(end_at, datetime):
        return {"error": "Start and end must both be dates (all-day) or both be times."}
    if end_at <= start_at:
        return {"error": f"End ({end}) must be after start ({start})."}
    body = {"summary": title, "start": _when(start_at), "end": _when(end_at)}
    if description:
        body["description"] = description
    event = _calendar().events().insert(calendarId=CALENDAR, body=body).execute()
    return _compact(event)


@mcp.tool()
@google_tool
def delete_event(event_id: str) -> dict:
    """Delete a calendar event by its id. Find the id with list_events or
    search_events first. Returns the deleted event so it can be restored."""
    calendar = _calendar()
    event = _live_event(calendar, event_id)  # refuses ids of already-deleted events
    calendar.events().delete(calendarId=CALENDAR, eventId=event_id).execute()
    return {"deleted": True, **_compact(event)}


if __name__ == "__main__":
    mcp.run()
