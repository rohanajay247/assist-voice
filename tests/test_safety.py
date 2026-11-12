"""The two safety gates: the static check on generated tool code, and the
default-deny approval rule. If either quietly breaks, a test here fails.

Run: uv run pytest tests/test_safety.py
"""
import pytest

from backend.assist.graph.agent import SAFE_TOOLS, needs_approval
from backend.assist.toolbuilder.checks import check_code

VALID_SERVER = '''
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("adder")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    mcp.run()
'''


def with_line(line: str) -> str:
    """The valid server plus one extra line inside the tool."""
    return VALID_SERVER.replace('    return a + b', f'    {line}\n    return a + b')


# ---------- check_code ----------

def test_minimal_fastmcp_server_passes():
    assert check_code(VALID_SERVER, needs_network=False) == []


@pytest.mark.parametrize("line", [
    "import os",
    "open('/etc/passwd')",
    "__import__('os')",
])
def test_escape_hatches_are_rejected(line):
    assert check_code(with_line(line), needs_network=False) != []


def test_httpx_needs_network():
    code = with_line("import httpx")
    assert check_code(code, needs_network=False) != []
    assert check_code(code, needs_network=True) == []


# ---------- needs_approval (default-deny) ----------

def call(name: str, **args) -> dict:
    return {"name": name, "args": args}


def test_safe_tool_runs_without_asking():
    assert "list_notes" in SAFE_TOOLS
    assert needs_approval(call("list_notes")) is False


def test_unknown_tool_needs_approval():
    assert needs_approval(call("some_tool_nobody_listed")) is True


def test_write_tool_needs_approval():
    assert needs_approval(call("delete_note", id=1)) is True
