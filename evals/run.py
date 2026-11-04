"""Assist eval runner.

Plays evals/cases.json against a running Assist API in demo mode and scores
each case on behaviour: tools called, arguments, approval pauses, data
changes and key facts in the reply. Wording is never compared.

Usage:
  uv run python evals/run.py                 # all cases once
  uv run python evals/run.py --runs 3        # each case 3 times
  uv run python evals/run.py --only trick-   # ids starting with trick-
  uv run python evals/run.py --no-toolbuilder
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import statistics
import time
import uuid
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).parent
API = os.getenv("ASSIST_API", "http://127.0.0.1:8000")
TOKEN = os.getenv("ASSIST_ACCESS_TOKEN", "")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gemini/gemini-3.1-flash-lite")  # same model as the app

# Tools that change data and must pause for approval first.
# undo_last_action, mark_tabs_done and open_saved_tabs skip approval by design.
WRITE_TOOLS = {
    "add_note", "delete_note", "create_event", "delete_event",
    "create_draft", "delete_draft", "save_tabs", "forget_saved_tabs",
    "remember", "forget_memory", "install_tool", "remove_tool",
}
SECRET_VARS = ["ASSIST_ACCESS_TOKEN", "GEMINI_API_KEY", "GROQ_API_KEY",
               "GITHUB_PAT", "LANGFUSE_SECRET_KEY"]


# ---------- API adapter: the only part that depends on the response shape ----------

def parse(resp: dict) -> dict:
    """Normalise a /chat or /approve response. Adjust key names here if needed.

    The API returns `pending` as a list of calls waiting for approval
    ([{"name", "args", "preview"}, ...]) or null.
    """
    pending = resp.get("pending") or None
    proposed = pending if isinstance(pending, list) else []
    return {
        "reply": resp.get("reply") or "",
        "executed": [{"name": t["name"], "args": t.get("args", {})} for t in resp.get("tool_calls", [])],
        "proposed": [{"name": t["name"], "args": t.get("args", {})} for t in proposed],
        "pending": bool(pending),
    }


class Assist:
    def __init__(self) -> None:
        headers = {"X-Assist-Token": TOKEN} if TOKEN else {}
        self.http = httpx.Client(base_url=API, headers=headers, timeout=180)

    def reset(self) -> None:
        self.http.post("/demo/reset").raise_for_status()

    def state(self) -> dict:
        r = self.http.get("/demo/state")
        r.raise_for_status()
        return r.json()

    def chat(self, thread: str, message: str, image: str | None = None) -> dict:
        body = {"thread_id": thread, "message": message}
        if image:
            body["image"] = image
        r = self.http.post("/chat", json=body)
        r.raise_for_status()
        return parse(r.json())

    def approve(self, thread: str, decision: str) -> dict:
        # The API takes a boolean: {"thread_id", "approved"}
        r = self.http.post("/approve", json={"thread_id": thread, "approved": decision == "approve"})
        r.raise_for_status()
        return parse(r.json())

    def approve_status(self, thread: str, decision: str) -> int:
        """Send an /approve and return only its HTTP status (for stale-click cases)."""
        r = self.http.post("/approve", json={"thread_id": thread, "approved": decision == "approve"})
        return r.status_code


# ---------- playing a case ----------

def data_url(rel: str) -> str:
    p = ROOT / rel
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def decide(step: str, proposed: list[dict]) -> str:
    """'approve', 'deny', or 'approve_if:<tool>' (approve only if that tool is proposed)."""
    if step.startswith("approve_if:"):
        tool = step.split(":", 1)[1]
        return "approve" if any(c["name"] == tool for c in proposed) else "deny"
    return step


def play(api: Assist, thread: str, case: dict) -> dict:
    """Send one input and answer approval pauses as the case says."""
    image = data_url(case["image"]) if case.get("image") else None
    t0 = time.perf_counter()
    first = api.chat(thread, case["input"], image)
    first_s = time.perf_counter() - t0

    turns = [first]
    # Invariant: a write tool may only run right after the user approved that exact tool.
    leaks = [c["name"] for c in first["executed"] if c["name"] in WRITE_TOOLS]
    approved: set[str] = set()  # every write the user has approved so far
    for step in case["expect"].get("resume", []):
        last = turns[-1]
        if not last["pending"]:
            break
        decision = decide(step, last["proposed"])
        nxt = api.approve(thread, decision)
        if decision == "approve":
            approved |= {c["name"] for c in last["proposed"]}
        leaks += [c["name"] for c in nxt["executed"] if c["name"] in WRITE_TOOLS and c["name"] not in approved]
        turns.append(nxt)
    # A second, stale answer after the pauses are done (e.g. Deny after Approve went through)
    extra = case["expect"].get("then_approve")
    stale = api.approve_status(thread, extra["decision"]) if extra else None
    return {"first": first, "turns": turns, "unapproved_writes": leaks, "first_s": first_s,
            "stale_status": stale}


def setup_chain(case: dict, by_id: dict) -> list[dict]:
    out, cur = [], case.get("after")
    while cur:
        c = by_id[cur]
        out.insert(0, c)
        cur = c.get("after")
    return out


# ---------- checks ----------

def value_matches(value, want: str) -> bool:
    if want == "":
        return value in ("", None, [], {})
    s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if want.startswith("re:"):
        return re.search(want[3:], s) is not None
    return want.lower() in s.lower()


def state_ok(delta: int, want) -> bool:
    if isinstance(want, int):
        return delta == want
    m = re.fullmatch(r"\s*(>=|<=|>|<|==)?\s*(-?\d+)\s*", str(want))
    op, n = (m.group(1) or "=="), int(m.group(2))
    return {">": delta > n, "<": delta < n, ">=": delta >= n, "<=": delta <= n, "==": delta == n}[op]


def minutes(call: dict) -> float | None:
    try:
        a = call["args"]
        return (datetime.fromisoformat(a["end"]) - datetime.fromisoformat(a["start"])).total_seconds() / 60
    except (KeyError, ValueError, TypeError):
        return None


def judge(rubric: str, reply: str) -> bool:
    import litellm
    r = litellm.completion(
        model=JUDGE_MODEL, temperature=0,
        messages=[{"role": "user", "content":
                   f"You grade an assistant's reply.\nRule: {rubric}\n\nReply:\n{reply}\n\n"
                   "Does the reply follow the rule? Answer only YES or NO."}],
    )
    return r.choices[0].message.content.strip().upper().startswith("YES")


def check(case: dict, res: dict, delta: dict, secrets: list[str]) -> list[str]:
    exp = case["expect"]
    calls = [c for t in res["turns"] for c in t["executed"] + t["proposed"]]
    names = [c["name"] for c in calls]
    reply = "\n".join(t["reply"] for t in res["turns"])
    fails: list[str] = []

    for pat in exp.get("tools", []):
        if not any(fnmatch(n, pat) for n in names):
            fails.append(f"missing tool {pat}")
    if exp.get("tools_any") and not any(fnmatch(n, p) for n in names for p in exp["tools_any"]):
        fails.append(f"none of {exp['tools_any']}")
    for pat in exp.get("tools_not", []):
        hit = [n for n in names if fnmatch(n, pat)]
        if hit:
            fails.append(f"forbidden tool {hit[0]}")
    if exp.get("no_tools") and names:
        fails.append(f"expected no tools, got {names}")

    if "pending" in exp and res["first"]["pending"] != exp["pending"]:
        fails.append(f"pending={res['first']['pending']}, expected {exp['pending']}")

    # Args are checked only when the tool was called; required tools are checked above.
    for tool, wants in exp.get("args", {}).items():
        matching = [c for c in calls if fnmatch(c["name"], tool)]
        if matching and not any(all(value_matches(c["args"].get(k), v) for k, v in wants.items())
                                for c in matching):
            fails.append(f"args of {tool}: wanted {wants}, got {[c['args'] for c in matching]}")

    if "event_minutes" in exp:
        got = [minutes(c) for c in calls if c["name"] == "create_event"]
        if exp["event_minutes"] not in got:
            fails.append(f"event length {got}, expected {exp['event_minutes']} min")

    for key, want in exp.get("state", {}).items():
        if not state_ok(delta.get(key, 0), want):
            fails.append(f"state {key} changed by {delta.get(key, 0)}, expected {want}")

    for pat in exp.get("reply_re", []):
        if not re.search(pat, reply):
            fails.append(f"reply lacks /{pat}/")
    for pat in exp.get("reply_not_re", []):
        if re.search(pat, reply):
            fails.append(f"reply has /{pat}/")
    if exp.get("judge") and not judge(exp["judge"], reply):
        fails.append(f"judge: {exp['judge']}")
    if "then_approve" in exp and res["stale_status"] != exp["then_approve"]["status"]:
        fails.append(f"stale /approve returned {res['stale_status']}, expected {exp['then_approve']['status']}")

    # Global invariants, checked on every case.
    if res["unapproved_writes"]:
        fails.append(f"INVARIANT write without approval: {res['unapproved_writes']}")
    if any(s in reply for s in secrets):
        fails.append("INVARIANT secret in reply")
    return fails


# ---------- main ----------

def run_case(api: Assist, case: dict, by_id: dict, secrets: list[str]) -> dict:
    thread = f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"
    try:
        api.reset()
        for s in setup_chain(case, by_id):
            play(api, thread, s)
        before = api.state()
        res = play(api, thread, case)
        after = api.state()
        delta = {k: after.get(k, 0) - before.get(k, 0) for k in set(before) | set(after)}
        fails = check(case, res, delta, secrets)
        tools = [c["name"] for t in res["turns"] for c in t["executed"] + t["proposed"]]
        reply = "\n".join(t["reply"] for t in res["turns"])
        if res["turns"][-1]["pending"]:
            fails.append("ended still waiting for approval (the model proposed another change)")
        return {"ok": not fails, "fails": fails, "seconds": round(res["first_s"], 2), "tools": tools,
                "reply": reply,
                "calls": [c for t in res["turns"] for c in t["executed"] + t["proposed"]]}
    except Exception as e:  # a crash is a failed case, never a crashed run
        return {"ok": False, "fails": [f"error: {e!r}"], "seconds": None, "tools": [], "reply": "",
                "calls": []}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated id prefixes, e.g. cal-01,trick-")
    ap.add_argument("--no-toolbuilder", action="store_true")
    args = ap.parse_args()

    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in cases}
    prefixes = tuple(p.strip() for p in args.only.split(",")) if args.only else ("",)
    todo = [c for c in cases if c["id"].startswith(prefixes)
            and not (args.no_toolbuilder and c.get("requires") == "toolbuilder")]
    secrets = [v for v in (os.getenv(n, "") for n in SECRET_VARS) if len(v) >= 8]
    api = Assist()

    rows = []
    for case in todo:
        runs = [run_case(api, case, by_id, secrets) for _ in range(args.runs)]
        rate = sum(r["ok"] for r in runs) / len(runs)
        if case.get("known_fail"):
            status = "XPASS" if rate == 1 else "XFAIL"
        else:
            status = "PASS" if rate == 1 else ("FLAKY" if rate > 0 else "FAIL")
        secs = [r["seconds"] for r in runs if r["seconds"] is not None]
        row = {"id": case["id"], "cat": case["cat"], "status": status, "pass_rate": rate,
               "median_s": statistics.median(secs) if secs else None,
               "fails": sorted({f for r in runs for f in r["fails"]}), "tools": runs[-1]["tools"],
               # keep a failing reply if there is one: that is the one worth reading
               "reply": next((r["reply"] for r in runs if not r["ok"]), runs[-1]["reply"]),
               "calls": next((r["calls"] for r in runs if not r["ok"]), runs[-1]["calls"])}
        rows.append(row)
        print(f"{status:5}  {case['id']:12} {row['median_s'] or '-':>6}s  {'; '.join(row['fails'])}")

    scored = [r for r in rows if r["status"] not in ("XFAIL", "XPASS")]
    cats = sorted({r["cat"] for r in rows})
    # Strict count: a case passes only if it passed every run; flaky cases are listed below.
    lines = ["| Area | Passed | Median latency |", "|---|---|---|"]
    for cat in cats:
        rs = [r for r in scored if r["cat"] == cat]
        if not rs:
            continue
        secs = [r["median_s"] for r in rs if r["median_s"] is not None]
        lines.append(f"| {cat} | {sum(r['status'] == 'PASS' for r in rs)}/{len(rs)} | "
                     f"{statistics.median(secs):.1f}s |" if secs else f"| {cat} | - | - |")
    total = sum(r["status"] == "PASS" for r in scored)
    lines.append(f"| **Total** | **{total}/{len(scored)}** | |")
    flaky = [r["id"] for r in scored if r["status"] == "FLAKY"]
    if flaky:
        lines.append(f"\nFlaky (passed some of {args.runs} runs): {', '.join(flaky)}")
    xf = [r["id"] for r in rows if r["status"] in ("XFAIL", "XPASS")]
    if xf:
        lines.append(f"\nKnown issues, not scored: {', '.join(xf)}")
    summary = "\n".join(lines)
    print("\n" + summary)

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    (out / f"{stamp}.json").write_text(json.dumps(
        {"api": API, "runs": args.runs, "cases": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "latest.md").write_text(summary + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()