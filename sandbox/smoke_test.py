"""Runs INSIDE the sandbox container.

Starts /tool/server.py over stdio like Assist would, lists its tools and
calls each test case from /tool/cases.json. Prints ONE JSON line to stdout:

    {"tools": [...], "passed": 3, "failed": 0, "results": [...], "errors": [...]}

A case looks like:
    {"tool": "count_workdays", "args": {...}, "expect": 5}
    {"tool": "slugify", "args": {...}, "expect_contains": "hello-world"}
With neither key, a case passes if the call returns without an error.
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOOL_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tool")
CALL_TIMEOUT = 10  # seconds per tool call
MAX_TEXT = 500     # result text kept in the report


def result_text(result) -> str:
    return "".join(getattr(b, "text", "") for b in result.content)


def check(case: dict, text: str) -> str | None:
    """None if the case passed, else why not."""
    if "expect" in case:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = text
        if value != case["expect"]:
            return f"expected {case['expect']!r}, got {value!r}"
    if "expect_contains" in case and str(case["expect_contains"]) not in text:
        return f"expected text containing {case['expect_contains']!r}"
    return None


async def run() -> dict:
    report = {"tools": [], "passed": 0, "failed": 0, "results": [], "errors": []}
    cases = json.loads((TOOL_DIR / "cases.json").read_text(encoding="utf-8"))
    params = StdioServerParameters(command=sys.executable, args=[str(TOOL_DIR / "server.py")])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), CALL_TIMEOUT)
            listed = (await asyncio.wait_for(session.list_tools(), CALL_TIMEOUT)).tools
            report["tools"] = [
                {"name": t.name, "description": (t.description or "").strip()} for t in listed
            ]
            names = {t.name for t in listed}

            if not listed:
                report["errors"].append("server exposes no tools")
            untested = names - {c.get("tool") for c in cases}
            if untested:
                report["errors"].append(f"tools without a test case: {sorted(untested)}")

            for case in cases:
                name, args = case.get("tool"), case.get("args", {})
                entry = {"tool": name, "args": args}
                if name not in names:
                    entry["error"] = f"unknown tool {name!r}"
                else:
                    try:
                        result = await asyncio.wait_for(
                            session.call_tool(name, args), CALL_TIMEOUT
                        )
                        text = result_text(result)
                        entry["output"] = text[:MAX_TEXT]
                        if result.isError:
                            entry["error"] = f"tool raised: {text[:200]}"
                        else:
                            why = check(case, text)
                            if why:
                                entry["error"] = why
                    except asyncio.TimeoutError:
                        entry["error"] = f"timed out after {CALL_TIMEOUT}s"
                if "error" in entry:
                    report["failed"] += 1
                else:
                    report["passed"] += 1
                report["results"].append(entry)
    return report


def main() -> None:
    try:
        report = asyncio.run(run())
    except BaseException as e:  # server crashed on start, bad cases.json, ...
        msg = str(e) or e.__class__.__name__
        if hasattr(e, "exceptions"):  # anyio wraps errors in ExceptionGroups
            msg = "; ".join(str(x) or x.__class__.__name__ for x in e.exceptions)
        report = {"tools": [], "passed": 0, "failed": 0, "results": [],
                  "errors": [f"server failed: {msg}"[:500]]}
    print(json.dumps(report))


if __name__ == "__main__":
    main()
