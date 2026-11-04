"""Demo mode: Assist on fake data.

DEMO_MODE=true swaps the Google, GitHub, notes and standup servers and the
browser extension for fakes backed by one SQLite file (demo.db, gitignored),
seeded from seed.json. Tool names, arguments and output shapes match the
real ones, so routing, approvals, undo and the step panel work unchanged.
Weather stays live. Used for the evals and the shareable hosted demo.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # read before agent.py's load_dotenv(): browser/memory/actions decide their DB on import

DEMO_MODE = os.getenv("DEMO_MODE", "").strip().lower() in {"true", "1", "yes", "on"}
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


def db_path(normal: Path) -> Path:
    """The demo DB in demo mode, otherwise the module's own DB."""
    return DB_PATH if DEMO_MODE else normal


def servers(real: dict) -> dict:
    """In demo mode: the real servers minus Google/GitHub/notes/standup, plus their fakes.
    Weather stays live. Outside demo mode: `real` unchanged."""
    if not DEMO_MODE:
        return real
    # stdio servers get a minimal environment; pass on what the fakes need
    env = {"DEMO_MODE": "true", "ASSIST_NOW": os.getenv("ASSIST_NOW", "")}
    fakes = {
        name: {"command": sys.executable, "args": ["-m", module], "transport": "stdio", "env": env}
        for name, module in FAKES.items()
    }
    kept = {name: cfg for name, cfg in real.items() if name not in FAKES}
    print(f"DEMO_MODE: fake {', '.join(FAKES)}; live {', '.join(kept) or 'none'}")
    return {**kept, **fakes}
