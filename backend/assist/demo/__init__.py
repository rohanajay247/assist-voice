"""Demo mode: Assist on fake data.

DEMO_MODE=true swaps the Google, GitHub, notes and standup servers and the
browser extension for fakes backed by one SQLite file (demo.db, gitignored),
seeded from seed.json. Tool names, arguments and output shapes match the
real ones, so routing, approvals, undo and the step panel work unchanged.
Weather stays live. Used for the evals and the shareable hosted demo.
"""
import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv
from backend.assist import clock  # the resolved timezone, passed on to the stdio servers

log = logging.getLogger(__name__)

load_dotenv()  # read before agent.py's load_dotenv(): browser/memory/actions decide their DB on import

TRUE = {"true", "1", "yes", "on"}
# Public demo (the hosted demo for strangers): demo data in a sandbox per visitor,
# no tool-building, no extension, limits. Implies DEMO_MODE. See demo/public.py.
PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "").strip().lower() in TRUE
DEMO_MODE = PUBLIC_DEMO or os.getenv("DEMO_MODE", "").strip().lower() in TRUE
# Demo data, but the real browser extension for tabs (the demo video's tabs scene)
REAL_BROWSER = (DEMO_MODE and not PUBLIC_DEMO
                and os.getenv("DEMO_REAL_BROWSER", "").strip().lower() in TRUE)
if PUBLIC_DEMO:
    # Read by agent.py on import (after this module): no build tools, no built tools
    os.environ["TOOLBUILDER_ENABLED"] = "false"
HERE = Path(__file__).parent
DB_PATH = HERE / "demo.db"  # *.db is gitignored
SEED_PATH = HERE / "seed.json"

# Fake MCP servers, started like the real ones (stdio), same server names so
# each tool lands in the same routing group
FAKES = {
    "notes": "backend.assist.demo.fake_notes",
    "standup": "backend.assist.demo.fake_standup",
    "github": "backend.assist.demo.fake_github",
    "google": "backend.assist.demo.fake_google",
}


# Public demo: the visitor's own DB file, set per request (demo/public.py). A
# ContextVar follows the request into the graph's nodes and tools.
_session_db: ContextVar[Path | None] = ContextVar("demo_session_db", default=None)


def db_path(normal: Path) -> Path:
    """The DB to use right now: the visitor's in public demo, the shared demo DB in
    demo mode, otherwise the module's own DB. Called on every connect."""
    if PUBLIC_DEMO:
        path = _session_db.get()
        if path is None:  # fail closed: never fall back to a shared file
            raise RuntimeError("Public demo: data access outside a visitor session")
        return path
    return DB_PATH if DEMO_MODE else normal


@contextmanager
def use_db(path: Path):
    """Run the block on this DB file (a visitor's sandbox, or the public demo template)."""
    token = _session_db.set(path)
    try:
        yield
    finally:
        _session_db.reset(token)


def session_key() -> str:
    """Which visitor this is ('' outside public demo), for per-visitor RAM state."""
    path = _session_db.get()
    return str(path) if path else ""


def servers(real: dict) -> dict:
    """In demo mode: the real servers minus Google/GitHub/notes/standup, plus their fakes.
    Weather stays live. Outside demo mode: `real`, with the timezone and GOOGLE_CALENDAR_ID passed on."""
    if not DEMO_MODE:
        # stdio servers only inherit a few system variables, so pass on the timezone
        # (one resolved value, so every server agrees) and the calendar choice
        for name in ("google", "standup"):
            if name in real:
                env = {**real[name].get("env", {}), "ASSIST_TIMEZONE": clock.TZ_NAME}
                calendar = os.getenv("GOOGLE_CALENDAR_ID", "").strip()
                if name == "google" and calendar:
                    env["GOOGLE_CALENDAR_ID"] = calendar
                real[name] = {**real[name], "env": env}
        return real
    # stdio servers get a minimal environment; pass on what the fakes need
    env = {"DEMO_MODE": "true", "ASSIST_NOW": os.getenv("ASSIST_NOW", ""),
           "ASSIST_TIMEZONE": clock.TZ_NAME}
    fakes = {
        name: {"command": sys.executable, "args": ["-m", module], "transport": "stdio", "env": env}
        for name, module in FAKES.items()
    }
    kept = {name: cfg for name, cfg in real.items() if name not in FAKES}
    log.info(f"DEMO_MODE: fake {', '.join(FAKES)}; live {', '.join(kept) or 'none'}")
    return {**kept, **fakes}
