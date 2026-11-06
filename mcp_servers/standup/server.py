"""Standup MCP server: read-only git activity across local repos.

Answers "what did I do yesterday?" together with the calendar tools.
It only reads git history; the agent combines it with list_events.
"""

import os
import subprocess
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# stdio servers get a stripped-down environment, so load .env explicitly
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# The user's timezone (IANA name). Assist Voice passes its own setting on
# (ASSIST_TIMEZONE, else the computer's timezone); run on its own, the same rule applies.
def _zone_name() -> str:
    name = os.getenv("ASSIST_TIMEZONE", "").strip()
    if name:
        return name
    try:
        from tzlocal import get_localzone_name
        return get_localzone_name() or "Europe/Berlin"
    except Exception:
        return "Europe/Berlin"


TZ = ZoneInfo(_zone_name())
MAX_DAYS = 14
MAX_COMMITS = 100
SEP = "\x1f"  # unit separator: can't appear in commit subjects

mcp = FastMCP("standup")


def _repos() -> list[Path]:
    raw = os.getenv("STANDUP_REPOS", "")
    return [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()]


def _git_log(repo: Path, since: str, until: str) -> list[dict]:
    args = [
        "git", "-C", str(repo), "log",
        "--branches",      # all local branches, not just the checked-out one
        "--source",        # lets %S show which branch each commit came from
        "--no-merges",
        f"--since={since}",
        f"--until={until}",
        f"--pretty=format:%H{SEP}%S{SEP}%cI{SEP}%s",
    ]
    author = os.getenv("GIT_AUTHOR_EMAIL")
    if author:
        args.append(f"--author={author}")

    out = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL,  # don't inherit the MCP stdio pipe (hangs on Windows)
        errors="replace", timeout=10, check=True,
    ).stdout

    commits = []
    for line in out.splitlines():
        parts = line.split(SEP, 3)
        if len(parts) != 4:
            continue
        sha, ref, when, subject = parts
        local = datetime.fromisoformat(when).astimezone(TZ)
        commits.append({
            "repo": repo.name,
            "branch": ref.removeprefix("refs/heads/"),
            "time": local.strftime("%Y-%m-%dT%H:%M"),
            "message": subject,
            "sha": sha[:7],
        })
    return commits


@mcp.tool()
def get_git_activity(date_from: str, date_to: str | None = None) -> dict:
    """Commits by the user across local repos, local dates, inclusive.

    date_from and date_to are YYYY-MM-DD. Omit date_to for a single day.
    Returns commits sorted by time, a count per repo, and per-repo errors.
    """
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to) if date_to else start
    except ValueError:
        return {"error": "Dates must be YYYY-MM-DD."}
    if end < start:
        return {"error": "date_to must not be before date_from."}
    if (end - start).days >= MAX_DAYS:
        return {"error": f"Range too long; max {MAX_DAYS} days."}

    repos = _repos()
    if not repos:
        return {"error": "STANDUP_REPOS is not set."}

    # Explicit offsets so git doesn't depend on the machine's timezone
    since = datetime.combine(start, time.min, TZ).isoformat()
    until = datetime.combine(end + timedelta(days=1), time.min, TZ).isoformat()

    commits, errors = [], []
    for repo in repos:
        if not (repo / ".git").exists():
            errors.append({"repo": repo.name, "error": "not a git repo or path missing"})
            continue
        try:
            commits.extend(_git_log(repo, since, until))
        except subprocess.CalledProcessError as e:
            errors.append({"repo": repo.name, "error": (e.stderr or "git failed").strip()[:200]})
        except (subprocess.TimeoutExpired, OSError) as e:
            errors.append({"repo": repo.name, "error": str(e)[:200]})

    commits.sort(key=lambda c: c["time"])
    per_repo: dict[str, int] = {}
    for c in commits:
        per_repo[c["repo"]] = per_repo.get(c["repo"], 0) + 1

    result = {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "total": len(commits),
        "per_repo": per_repo,
        "commits": commits[:MAX_COMMITS],
    }
    if len(commits) > MAX_COMMITS:
        result["truncated"] = True
    if errors:
        result["errors"] = errors
    return result


if __name__ == "__main__":
    mcp.run()