"""Tool-building flow (Day 5): Assist writes a new MCP server, tests it in
Docker, and adds it only after the user approves.

    generate (generator.py)  ->  static check (checks.py)
      ->  sandbox test (sandbox.py)  ->  proposal (registry.py)
      ->  install_tool, approved like any write  ->  graph rebuilt with the new tools
"""
