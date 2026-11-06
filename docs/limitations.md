# Known limitations

[← Back to the README](../README.md)

- **Conversations live in memory.** Restarting the API (or `--reload`) loses all threads, and undo only covers the current thread. A persistent checkpointer is needed before a real deployment.
- **Slow tool calls.** Each MCP tool call starts a fresh server process, which adds about 2 seconds.
- **The steps panel isn't live.** It appears once the reply is done.
- **Single user.** One set of accounts, one browser extension connection.
- **Tool-building is local only.** It needs Docker on the same machine.
- **Quick tunnel URLs change on every start,** so an installed home-screen app breaks after a restart.
- **Google sign-in expires weekly** while the OAuth app is in Testing.
- **Time edges.** "Tomorrow" said after midnight lands a day late, and commits after midnight count to the next day in the standup.
- **Weather:** hyphenated districts like "Albstadt-Ebingen" aren't found.
- **Draft preview.** The approval card shows Gemini's draft text. Gmail gets a version with tidied line breaks, which can look slightly different.
- **Two safeguards live in the prompt and the UI, not in code.** Only the prompt stops parallel undo calls. Only the UI stops a new message while an approval is waiting.
- **Privacy on the free Gemini tier.** Messages and photos are processed by Google and may be used to improve their products.
- **Langfuse** shows no token or cost numbers for these calls, so cost per command isn't measured yet.
- **The evals are a smoke test, not a benchmark:** 41 cases and a few runs each.
