"""Demo standup server: get_git_activity with the same arguments and result shape
as mcp_servers/standup, reading the seed's git history instead of local repos."""
from datetime import date

from mcp.server.fastmcp import FastMCP

from backend.assist.demo.store import seed

MAX_DAYS = 14
mcp = FastMCP("standup")


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

    git = seed()["git"]
    commits = sorted(
        ({"repo": git["repo"], **c} for c in git["commits"]
         if start <= date.fromisoformat(c["time"][:10]) <= end),
        key=lambda c: c["time"],
    )
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "total": len(commits),
        "per_repo": {git["repo"]: len(commits)} if commits else {},
        "commits": commits,
    }


if __name__ == "__main__":
    mcp.run()
