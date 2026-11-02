"""Ask the tool-building model for a new MCP server, test it, retry on failure.

Flash-Lite, like the rest of Assist, to keep costs near zero. The sandbox
test and the retry loop catch its mistakes. TOOLBUILDER_MODEL in .env can
point at a stronger model; Flash-Lite stays as the fallback.
"""
import asyncio
import json
import os
import re
from pathlib import Path

import litellm

from backend.assist.toolbuilder.checks import check_code
from backend.assist.toolbuilder.sandbox import run_in_sandbox

DEFAULT_MODEL = "gemini/gemini-3.1-flash-lite"
MODELS = list(dict.fromkeys(m for m in (os.getenv("TOOLBUILDER_MODEL"), DEFAULT_MODEL) if m))
MAX_ATTEMPTS = 3  # first try + 2 fixes

TEMPLATE = '''from mcp.server.fastmcp import FastMCP

mcp = FastMCP("workdays")


@mcp.tool()
def count_workdays(start: str, end: str) -> int:
    """Count Monday-Friday days from start to end, both included.
    Use when the user asks how many working days are between two dates.
    `start` and `end` are ISO dates like '2026-11-02'."""
    ...


if __name__ == "__main__":
    mcp.run()
'''

SYSTEM = f"""You write small MCP tool servers in Python for a voice assistant.

Rules for server.py:
- One file. Use FastMCP exactly like this template:
```python
{TEMPLATE}```
- 1 to 3 tools. Type-hinted arguments, return str, int, float, bool, list or dict.
- Each docstring says what the tool does, when to use it, and the argument formats.
  The assistant decides when to call the tool from this docstring alone.
- Allowed imports only: math, statistics, decimal, fractions, random, datetime,
  zoneinfo, calendar, time, json, re, string, textwrap, unicodedata, difflib, html,
  itertools, functools, collections, dataclasses, typing, enum, uuid, hashlib,
  base64, binascii, urllib.parse, pydantic, and httpx ONLY if network is allowed.
- Never use eval, exec, open, files, os, sys, subprocess, getattr, globals or
  dunder attributes. No API keys: only public APIs that need no login.
- On bad input, return {{"error": "..."}} instead of raising.
- Network calls: httpx with timeout=10.

Also write cases.json: 3 to 6 test cases covering every tool, each
{{"tool": name, "args": {{...}}, "expect": exact JSON value}} for deterministic
results, or {{"tool": ..., "args": ..., "expect_contains": "text"}} when the
exact value can change (network data). Work the expected values out carefully.

Reply with exactly two fenced blocks: ```python (server.py) then ```json (cases)."""


def _blocks(text: str) -> tuple[str, list] | None:
    code = re.search(r"```python\s*\n(.*?)```", text, re.S)
    cases = re.search(r"```json\s*\n(.*?)```", text, re.S)
    if not code or not cases:
        return None
    try:
        parsed = json.loads(cases.group(1))
    except json.JSONDecodeError:
        return None
    return (code.group(1).strip() + "\n", parsed) if isinstance(parsed, list) else None


async def _ask(messages: list) -> tuple[str, str]:
    """Reply text and the model that answered. Falls back if a model fails."""
    last_error = None
    for model in MODELS:
        try:
            res = await litellm.acompletion(model=model, messages=messages, temperature=0.2)
            return res.choices[0].message.content or "", model
        except Exception as e:  # not on this key, quota, outage: try the next one
            print(f"Toolbuilder: {model} failed ({e.__class__.__name__})")
            last_error = e
    raise RuntimeError(f"no tool-building model worked: {last_error}")


def _feedback(problems: list[str], report: dict | None) -> str:
    lines = ["Your server failed. Fix it and reply with both blocks again."]
    lines += [f"- {p}" for p in problems]
    if report:
        lines += [f"- {e}" for e in report.get("errors", [])]
        lines += [
            f"- case {r['tool']}({json.dumps(r['args'])}): {r['error']}"
            for r in report.get("results", []) if "error" in r
        ]
    return "\n".join(lines)


async def generate_and_test(
    name: str, description: str, needs_network: bool, out_dir: Path
) -> dict:
    """Write out_dir/server.py + cases.json until the sandbox test passes.

    Returns {"ok", "attempts", "model", "report", "problems"}. On ok=False the
    last attempt's files stay in out_dir so the failure can be inspected.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    network = "Network access: ALLOWED (httpx)." if needs_network else "Network access: NONE."
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Server name: {name}\n{network}\nWhat it should do: {description}"},
    ]
    report, problems, model = None, [], None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        text, model = await _ask(messages)
        messages.append({"role": "assistant", "content": text})
        parsed = _blocks(text)
        if parsed is None:
            problems, report = ["reply must contain a ```python block and a ```json list"], None
        else:
            code, cases = parsed
            (out_dir / "server.py").write_text(code, encoding="utf-8")
            (out_dir / "cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
            problems = check_code(code, needs_network)
            report = None
            if not problems:
                # subprocess in a thread: works with any event loop on Windows
                report = await asyncio.to_thread(run_in_sandbox, out_dir, needs_network)
                if report["failed"] == 0 and not report["errors"] and report["passed"] > 0:
                    return {"ok": True, "attempts": attempt, "model": model,
                            "report": report, "problems": []}
                if any(e.startswith(("Docker", "sandbox image")) for e in report["errors"]):
                    break  # the model can't fix a missing Docker
        messages.append({"role": "user", "content": _feedback(problems, report)})

    return {"ok": False, "attempts": attempt, "model": model, "report": report, "problems": problems}
