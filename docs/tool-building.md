# Tool-building

[← Back to the README](../README.md)

Ask for something no tool can do, and Assist Voice can offer to write a small new MCP server. The code is checked statically and tested in a Docker sandbox (no network, read-only, no secrets). You approve the install after seeing the code and test results. Built tools always run inside the sandbox.

This needs Docker Desktop running and a one-time image build:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_sandbox.ps1
```

```bash
docker build -t assist-sandbox sandbox
```

No Docker? Set `TOOLBUILDER_ENABLED=false` to hide it.
