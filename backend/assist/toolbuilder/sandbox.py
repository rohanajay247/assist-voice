"""Run generated MCP servers in Docker: for the test, and for real after approval.

The container gets no secrets and no env vars from Assist, runs as a
non-root user with a read-only filesystem, a memory/CPU/process cap and,
unless the tool was approved with network access, no network at all.
"""
import json
import subprocess
import uuid
from pathlib import Path

IMAGE = "assist-sandbox"
TEST_TIMEOUT = 60  # seconds for the whole smoke test (container start included)

LIMITS = [
    "--read-only", "--tmpfs", "/tmp:size=16m",
    "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
    "--user", "10001",
]


def docker_args(tool_dir: Path, needs_network: bool, interactive: bool = False) -> list[str]:
    """`docker run` arguments for one generated server folder (mounted read-only)."""
    source = str(Path(tool_dir).resolve())
    return [
        "run", "--rm", *(["-i"] if interactive else []),
        "--network", "bridge" if needs_network else "none",
        *LIMITS,
        # --mount, not -v: Windows paths like D:\... contain a colon
        "--mount", f"type=bind,source={source},target=/tool,readonly",
        IMAGE,
    ]


def runtime_server(tool_dir: Path, needs_network: bool) -> dict:
    """MultiServerMCPClient entry: the approved server, still inside the sandbox."""
    return {
        "command": "docker",
        "args": docker_args(tool_dir, needs_network, interactive=True)
        + ["python", "/tool/server.py"],
        "transport": "stdio",
    }


def docker_ready() -> str | None:
    """None if Docker runs and the image exists, else what the user must do."""
    try:
        res = subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True, text=True, timeout=20
        )
    except FileNotFoundError:
        return "Docker is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return "Docker did not answer; is Docker Desktop running?"
    if res.returncode != 0:
        if "No such image" in res.stderr or "No such object" in res.stderr:
            return "sandbox image missing: run scripts/build_sandbox.ps1"
        return "Docker is not running: start Docker Desktop"
    return None


def run_in_sandbox(tool_dir: Path, needs_network: bool) -> dict:
    """Smoke-test server.py + cases.json in tool_dir. Returns the smoke test's report:
    {"tools", "passed", "failed", "results", "errors"}. Never raises."""
    problem = docker_ready()
    if problem:
        return {"tools": [], "passed": 0, "failed": 0, "results": [], "errors": [problem]}

    name = f"assist-test-{uuid.uuid4().hex[:8]}"
    args = docker_args(tool_dir, needs_network)
    args.insert(2, f"--name={name}")  # after "run --rm", so we can kill it on timeout
    try:
        res = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=TEST_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return {"tools": [], "passed": 0, "failed": 0, "results": [],
                "errors": [f"test took longer than {TEST_TIMEOUT}s"]}

    last_line = (res.stdout.strip().splitlines() or [""])[-1]
    try:
        return json.loads(last_line)
    except json.JSONDecodeError:
        err = (res.stderr or res.stdout).strip()[-500:] or f"exit code {res.returncode}"
        return {"tools": [], "passed": 0, "failed": 0, "results": [],
                "errors": [f"sandbox failed: {err}"]}
