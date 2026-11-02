"""Static check of generated server code, before it ever runs.

The Docker sandbox is the real wall; this is the cheap first line. It
rejects code that imports anything outside a small allowlist or reaches
for escape hatches (eval, open, dunder attributes), and gives the model a
precise error to fix.
"""
import ast

MAX_CODE_BYTES = 20_000

# Pure-Python standard library modules a small tool may use
SAFE_MODULES = {
    "math", "cmath", "statistics", "decimal", "fractions", "random",
    "datetime", "zoneinfo", "calendar", "time",
    "json", "re", "string", "textwrap", "unicodedata", "difflib", "html",
    "itertools", "functools", "collections", "dataclasses", "typing", "enum",
    "uuid", "hashlib", "base64", "binascii", "urllib.parse",
    "mcp.server.fastmcp", "pydantic",
}
NETWORK_MODULES = {"httpx"}

BANNED_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "memoryview", "help", "exit", "quit",
}


def _allowed(module: str, allowed: set[str]) -> bool:
    """'collections.abc' is fine because 'collections' is; 'mcp' and 'urllib'
    are not listed bare, so only 'mcp.server.fastmcp' and 'urllib.parse' pass."""
    return module in allowed or module.split(".")[0] in allowed


def check_code(code: str, needs_network: bool) -> list[str]:
    """Problems found in the code. [] means it may go to the sandbox."""
    if len(code.encode()) > MAX_CODE_BYTES:
        return [f"code is longer than {MAX_CODE_BYTES} bytes"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error on line {e.lineno}: {e.msg}"]

    allowed = SAFE_MODULES | (NETWORK_MODULES if needs_network else set())
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _allowed(alias.name, allowed):
                    problems.append(f"line {node.lineno}: import {alias.name} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or not _allowed(node.module, allowed):
                problems.append(
                    f"line {node.lineno}: from {node.module or '.'} import is not allowed"
                )
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            problems.append(f"line {node.lineno}: {node.id} is not allowed")
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id != "__name__":
            problems.append(f"line {node.lineno}: {node.id} is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"line {node.lineno}: attribute {node.attr} is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f"line {node.lineno}: global/nonlocal is not allowed")

    if "FastMCP(" not in code or "mcp.run(" not in code:
        problems.append("server must create mcp = FastMCP(...) and call mcp.run()")
    if not needs_network and "httpx" in code:
        problems.append("httpx used but the tool was not built with network access")
    return list(dict.fromkeys(problems))  # no duplicates, order kept
