"""Demo GitHub server: read-only tools with the same names and arguments as
GitHub's hosted MCP server (read-only toolsets), answering from seed.json.

Like the real setup there are no write tools, so "open an issue" or "merge
PR 42" can't happen; build_graph's read-only check still runs on these.
"""
import re

from mcp.server.fastmcp import FastMCP

from backend.assist.demo.store import seed

mcp = FastMCP("github")


def _gh() -> dict:
    return seed()["github"]


def _url(path: str = "") -> str:
    g = _gh()
    return f"https://github.com/{g['owner']}/{g['repo']}{path}"


def _check_repo(owner: str, repo: str) -> dict | None:
    """None if owner/repo is the demo repo, else a 404-style error naming it."""
    g = _gh()
    if repo.lower().strip() == g["repo"] and owner.lower().strip() in (g["owner"], ""):
        return None
    return {"error": f"Not Found: {owner}/{repo}. The user's repository is {g['owner']}/{g['repo']}."}


def _pull(number: int) -> dict | None:
    return next((p for p in _gh()["pulls"] if p["number"] == int(number)), None)


def _pull_summary(p: dict) -> dict:
    return {
        "number": p["number"], "title": p["title"], "state": p["state"], "draft": p["draft"],
        "user": {"login": p["user"]}, "head": {"ref": p["head"]}, "base": {"ref": p["base"]},
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "html_url": _url(f"/pull/{p['number']}"),
    }


def _run_summary(r: dict) -> dict:
    return {k: r[k] for k in ("id", "name", "head_branch", "event", "status", "conclusion",
                               "run_number", "workflow_id", "created_at", "updated_at")} | {
        "html_url": _url(f"/actions/runs/{r['id']}")}


def _job_summary(j: dict, run_id: int) -> dict:
    return {"id": j["id"], "run_id": run_id, "name": j["name"], "status": j["status"],
            "conclusion": j["conclusion"],
            "steps": [{"name": s, "conclusion": j["conclusion"] if i == len(j["steps"]) - 1 else "success"}
                      for i, s in enumerate(j["steps"])]}


def _jobs():
    for r in _gh()["runs"]:
        for j in r["jobs"]:
            yield r, j


def _words_match(query: str, text: str) -> bool:
    """Free words must appear; qualifiers like is:pr or repo:x are ignored."""
    words = [w for w in query.split() if ":" not in w and w.upper() not in ("OR", "AND")]
    return all(w.lower() in text.lower() for w in words)


# ---------- context ----------

@mcp.tool()
def get_me() -> dict:
    """Get details of the authenticated GitHub user. Use this when a request is about the user's own profile for GitHub."""
    g = _gh()
    return {"login": g["login"], "name": "Rohan (demo)", "public_repos": 1,
            "html_url": f"https://github.com/{g['login']}"}


# ---------- repos ----------

@mcp.tool()
def search_repositories(query: str, minimal_output: bool = True, sort: str = "", order: str = "",
                        page: int = 1, perPage: int = 30) -> dict:
    """Find GitHub repositories by name, description, readme, topics, or other metadata."""
    g = _gh()
    return {"total_count": 1, "items": [{"full_name": f"{g['owner']}/{g['repo']}", "name": g["repo"],
                                         "owner": {"login": g["owner"]}, "private": False,
                                         "description": "Assist: a voice assistant across tools via MCP",
                                         "html_url": _url()}]}


@mcp.tool()
def list_branches(owner: str, repo: str, page: int = 1, perPage: int = 30) -> list | dict:
    """List branches in a GitHub repository"""
    return _check_repo(owner, repo) or [{"name": b, "protected": b == "main"} for b in _gh()["branches"]]


@mcp.tool()
def list_commits(owner: str, repo: str, sha: str = "", author: str = "", path: str = "",
                 since: str = "", until: str = "", page: int = 1, perPage: int = 30,
                 fields: list[str] | None = None) -> list | dict:
    """Get list of commits of a branch in a GitHub repository. Returns at least 30 results per page by default."""
    if err := _check_repo(owner, repo):
        return err
    commits = [c for c in reversed(seed()["git"]["commits"]) if not sha or c["branch"] == sha]
    return [{"sha": c["sha"], "commit": {"message": c["message"], "author": {"date": c["time"]}},
             "author": {"login": _gh()["login"]}} for c in commits]


@mcp.tool()
def get_commit(owner: str, repo: str, sha: str, detail: str = "none",
               page: int = 1, perPage: int = 30) -> dict:
    """Get details for a commit from a GitHub repository"""
    if err := _check_repo(owner, repo):
        return err
    c = next((c for c in seed()["git"]["commits"] if c["sha"].startswith(sha[:7])), None)
    if c is None:
        return {"error": f"Not Found: commit {sha}"}
    return {"sha": c["sha"], "commit": {"message": c["message"], "author": {"date": c["time"]}},
            "html_url": _url(f"/commit/{c['sha']}")}


# ---------- pull requests ----------

@mcp.tool()
def list_pull_requests(owner: str, repo: str, state: str = "open", head: str = "", base: str = "",
                       sort: str = "", direction: str = "", page: int = 1, perPage: int = 30,
                       fields: list[str] | None = None) -> list | dict:
    """List pull requests in a GitHub repository. If the user specifies an author, then DO NOT use this tool and use the search_pull_requests tool instead."""
    if err := _check_repo(owner, repo):
        return err
    return [_pull_summary(p) for p in _gh()["pulls"]
            if state == "all" or p["state"] == state]


@mcp.tool()
def search_pull_requests(query: str, owner: str = "", repo: str = "", sort: str = "", order: str = "",
                         page: int = 1, perPage: int = 30, fields: list[str] | None = None) -> dict:
    """Search for pull requests in GitHub repositories using issues search syntax already scoped to is:pr"""
    state = re.search(r"\bis:(open|closed)\b", query)
    items = [_pull_summary(p) for p in _gh()["pulls"]
             if _words_match(query, f"{p['title']} {p['body']}")
             and (not state or p["state"] == state.group(1))]
    return {"total_count": len(items), "items": items}


@mcp.tool()
def pull_request_read(method: str, owner: str, repo: str, pullNumber: int,
                      after: str = "", page: int = 1, perPage: int = 30) -> dict | list:
    """Get information on a specific pull request in GitHub repository.
    method: get, get_diff, get_status, get_files, get_commits, get_review_comments,
    get_reviews, get_comments, get_check_runs."""
    if err := _check_repo(owner, repo):
        return err
    p = _pull(pullNumber)
    if p is None:
        return {"error": f"Not Found: pull request #{pullNumber}"}
    run = next((r for r in _gh()["runs"] if r["head_branch"] == p["head"]), None)
    if method == "get":
        return {**_pull_summary(p), "body": p["body"], "mergeable": True,
                "comments": len(p["comments"]), "review_comments": len(p["review_comments"])}
    if method == "get_reviews":
        return [{"id": r["id"], "user": {"login": r["user"]}, "state": r["state"], "body": r["body"],
                 "submitted_at": r["submitted_at"]} for r in p["reviews"]]
    if method == "get_review_comments":
        return [{"id": c["id"], "user": {"login": c["user"]}, "path": c["path"], "line": c["line"],
                 "body": c["body"], "created_at": c["created_at"]} for c in p["review_comments"]]
    if method == "get_comments":
        return p["comments"]
    if method == "get_files":
        return [{"filename": f, "status": "modified"} for f in p["files"]]
    if method == "get_commits":
        return [{"sha": c["sha"], "commit": {"message": c["message"]}}
                for c in seed()["git"]["commits"] if c["branch"] == p["head"]]
    if method == "get_diff":
        return {"diff": "--- a/backend/auth/token.py\n+++ b/backend/auth/token.py\n"
                        "+    if token.expires_in < 300:\n+        token = refresh_token(token)\n"}
    if method in ("get_status", "get_check_runs"):
        if run is None:
            return {"state": "pending", "statuses": []}
        checks = [{"name": f"{run['name']} / {j['name']}", "status": j["status"],
                   "conclusion": j["conclusion"], "run_id": run["id"], "job_id": j["id"]}
                  for j in run["jobs"]]
        return {"state": run["conclusion"], "total_count": len(checks), "check_runs": checks}
    return {"error": f"Unknown method {method!r}"}


# ---------- issues ----------

@mcp.tool()
def list_issues(owner: str, repo: str, state: str = "OPEN", labels: list[str] | None = None,
                orderBy: str = "", direction: str = "", since: str = "", after: str = "",
                perPage: int = 30, fields: list[str] | None = None,
                field_filters: list | None = None) -> dict:
    """List issues in a GitHub repository. For pagination, use the 'endCursor' from the previous response's 'pageInfo' in the 'after' parameter."""
    if err := _check_repo(owner, repo):
        return err
    issues = [i for i in _gh()["issues"] if i["state"].upper() == state.upper()]
    return {"issues": issues, "totalCount": len(issues), "pageInfo": {"hasNextPage": False}}


@mcp.tool()
def search_issues(query: str, owner: str = "", repo: str = "", sort: str = "", order: str = "",
                  page: int = 1, perPage: int = 30, fields: list[str] | None = None) -> dict:
    """Search for issues in GitHub repositories using issues search syntax already scoped to is:issue"""
    items = [i for i in _gh()["issues"] if _words_match(query, f"{i['title']} {i['body']}")]
    return {"total_count": len(items), "items": items}


@mcp.tool()
def issue_read(method: str, owner: str, repo: str, issue_number: int,
               page: int = 1, perPage: int = 30) -> dict | list:
    """Get information about a specific issue in a GitHub repository.
    method: get, get_comments, get_sub_issues, get_parent, get_labels."""
    if err := _check_repo(owner, repo):
        return err
    issue = next((i for i in _gh()["issues"] if i["number"] == int(issue_number)), None)
    if issue is None:
        return {"error": f"Not Found: issue #{issue_number}"}
    return issue if method == "get" else []


# ---------- actions (CI) ----------

@mcp.tool()
def actions_list(method: str, owner: str, repo: str, resource_id: str = "",
                 workflow_runs_filter: dict | None = None, workflow_jobs_filter: dict | None = None,
                 page: int = 1, perPage: int = 30) -> dict:
    """Tools for listing GitHub Actions resources.
    method: list_workflows, list_workflow_runs, list_workflow_jobs (resource_id = run id),
    list_workflow_run_artifacts (resource_id = run id). Newest runs first."""
    if err := _check_repo(owner, repo):
        return err
    g = _gh()
    if method == "list_workflows":
        return {"total_count": len(g["workflows"]), "workflows": g["workflows"]}
    if method == "list_workflow_runs":
        branch = (workflow_runs_filter or {}).get("branch")
        runs = [_run_summary(r) for r in g["runs"] if not branch or r["head_branch"] == branch]
        return {"total_count": len(runs), "workflow_runs": runs}
    if method in ("list_workflow_jobs", "list_workflow_run_artifacts"):
        run = next((r for r in g["runs"] if str(r["id"]) == str(resource_id)), None)
        if run is None:
            return {"error": f"Not Found: workflow run {resource_id!r}"}
        if method == "list_workflow_run_artifacts":
            return {"total_count": 0, "artifacts": []}
        return {"total_count": len(run["jobs"]), "jobs": [_job_summary(j, run["id"]) for j in run["jobs"]]}
    return {"error": f"Unknown method {method!r}"}


@mcp.tool()
def actions_get(method: str, owner: str, repo: str, resource_id: str) -> dict:
    """Get details about specific GitHub Actions resources.
    method: get_workflow, get_workflow_run, get_workflow_job (resource_id = that id)."""
    if err := _check_repo(owner, repo):
        return err
    g = _gh()
    if method == "get_workflow":
        found = next((w for w in g["workflows"] if str(w["id"]) == str(resource_id)), None)
        return found or {"error": f"Not Found: workflow {resource_id!r}"}
    if method == "get_workflow_run":
        run = next((r for r in g["runs"] if str(r["id"]) == str(resource_id)), None)
        return _run_summary(run) if run else {"error": f"Not Found: workflow run {resource_id!r}"}
    if method == "get_workflow_job":
        found = next((_job_summary(j, r["id"]) for r, j in _jobs() if str(j["id"]) == str(resource_id)), None)
        return found or {"error": f"Not Found: job {resource_id!r}"}
    return {"error": f"{method} is not available in the demo"}


@mcp.tool()
def get_job_logs(owner: str, repo: str, job_id: int | None = None, run_id: int | None = None,
                 failed_only: bool = False, return_content: bool = False,
                 tail_lines: int = 500) -> dict:
    """Get logs for GitHub Actions workflow jobs. Use job_id for one job, or run_id
    with failed_only=true for every failed job in a run."""
    if err := _check_repo(owner, repo):
        return err
    picked = [(r, j) for r, j in _jobs()
              if (job_id is not None and j["id"] == int(job_id))
              or (job_id is None and run_id is not None and r["id"] == int(run_id)
                  and (not failed_only or j["conclusion"] == "failure"))]
    if not picked:
        return {"error": "No matching jobs. Pass job_id, or run_id (with failed_only=true)."}
    return {"logs": [{"job_id": j["id"], "job_name": j["name"], "run_id": r["id"],
                      "logs": "\n".join(j.get("log", "").splitlines()[-tail_lines:])}
                     for r, j in picked]}


if __name__ == "__main__":
    mcp.run()
