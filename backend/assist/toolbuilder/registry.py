"""Where built tools live.

    mcp_servers/generated/_proposals/<id>/   every build: server.py, cases.json, meta.json
                                              (gitignored; kept so undo can reinstall)
    mcp_servers/generated/<name>/            installed servers (committed)
    mcp_servers/generated/registry.json      which servers are installed

Installing copies a passed proposal into place and marks the registry as
changed; the API then rebuilds the graph so the new tools exist from the
next message on.
"""
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.assist.toolbuilder.checks import check_code
from backend.assist.toolbuilder.sandbox import runtime_server

ROOT = Path(__file__).resolve().parents[3] / "mcp_servers" / "generated"
PROPOSALS = ROOT / "_proposals"
REGISTRY = ROOT / "registry.json"

NAME = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
RESERVED = {"notes", "weather", "standup", "google", "github", "toolbuilder", "generated"}

_changed = False  # set by install/uninstall, read once by the API


def valid_name(name: str) -> str | None:
    """None if `name` can be a new server name, else why not."""
    if not NAME.match(name):
        return "name must be 3-31 lowercase letters, digits or _ and start with a letter"
    if name in RESERVED or name in installed():
        return f"a server called {name} already exists"
    return None


def installed() -> dict:
    if not REGISTRY.exists():
        return {}
    return json.loads(REGISTRY.read_text(encoding="utf-8")).get("servers", {})


def _save(servers: dict) -> None:
    global _changed
    ROOT.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps({"servers": servers}, indent=2) + "\n", encoding="utf-8")
    _changed = True


def consume_changed() -> bool:
    """True once after an install or uninstall (the graph must be rebuilt)."""
    global _changed
    changed, _changed = _changed, False
    return changed


def new_proposal() -> tuple[str, Path]:
    pid = uuid.uuid4().hex[:8]
    return pid, PROPOSALS / pid


def save_meta(pid: str, meta: dict) -> None:
    (PROPOSALS / pid / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_proposal(pid: str) -> dict | None:
    """meta + code + cases of a proposal, or None if there is no such proposal."""
    if not re.fullmatch(r"[0-9a-f]{8}", pid or ""):
        return None
    folder = PROPOSALS / pid
    if not (folder / "meta.json").exists():
        return None
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    meta["code"] = (folder / "server.py").read_text(encoding="utf-8")
    meta["cases"] = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    return meta


def install(pid: str) -> dict:
    """Copy a passed proposal into place. Returns a result dict for the tool."""
    p = load_proposal(pid)
    if p is None:
        return {"error": f"no tool proposal {pid}"}
    if not p.get("ok"):
        return {"error": f"proposal {pid} did not pass its tests; build it again"}
    if p["name"] in installed():
        return {"error": f"{p['name']} is already installed"}
    # The files could have been edited since the test: check them again
    problems = check_code(p["code"], p["needs_network"])
    if problems:
        return {"error": f"proposal {pid} no longer passes the check: {problems[0]}"}

    target = ROOT / p["name"]
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for f in ("server.py", "cases.json"):
        shutil.copy2(PROPOSALS / pid / f, target / f)

    servers = installed()
    servers[p["name"]] = {
        "description": p["description"],
        "needs_network": p["needs_network"],
        "tools": [t["name"] for t in p["report"]["tools"]],
        "proposal_id": pid,
        "model": p.get("model"),
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(servers)
    return {"installed": True, "name": p["name"], "proposal_id": pid,
            "tools": servers[p["name"]]["tools"]}


def uninstall(name: str) -> dict:
    servers = installed()
    if name not in servers:
        return {"error": f"no built tool called {name}"}
    entry = servers.pop(name)
    shutil.rmtree(ROOT / name, ignore_errors=True)
    _save(servers)
    # The proposal folder stays, so undo can install it again
    return {"removed": True, "name": name, "proposal_id": entry["proposal_id"],
            "tools": entry["tools"]}


def server_configs() -> dict:
    """MultiServerMCPClient entries for every installed server (run in Docker)."""
    return {
        name: runtime_server(ROOT / name, entry["needs_network"])
        for name, entry in installed().items()
    }
