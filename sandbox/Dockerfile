# Sandbox for tools Assist writes itself.
# Every generated MCP server is tested AND later run inside this image:
# no secrets, non-root, read-only code mount. Network is off unless the
# tool was approved with network access (see backend/assist/toolbuilder/sandbox.py).
#
# Build once:  powershell -ExecutionPolicy Bypass -File scripts/build_sandbox.ps1
FROM python:3.12-slim

# Same versions as uv.lock, so a tool that passes here behaves the same as our servers
RUN pip install --no-cache-dir "mcp==1.30.0" "httpx==0.28.1" tzdata

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin tool
COPY smoke_test.py /sandbox/smoke_test.py

# The generated server is mounted read-only at /tool at run time
WORKDIR /tool
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "/sandbox/smoke_test.py"]
