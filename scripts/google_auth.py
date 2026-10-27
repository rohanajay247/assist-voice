"""One-time Google sign-in for the Assist google MCP server.

Opens a browser, asks for the scopes in mcp_servers/google/server.py and saves
the token to secrets/google-token.json. Re-run it after changing SCOPES.

    uv run python scripts/google_auth.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so the server module (and its SCOPES) can be imported

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from mcp_servers.google.server import CLIENT_PATH, SCOPES, TOKEN_PATH  # noqa: E402


def main():
    if not CLIENT_PATH.exists():
        sys.exit(
            f"Missing {CLIENT_PATH}.\n"
            "Create a Desktop OAuth client in Google Cloud Console and save its JSON there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_PATH), SCOPES)
    # offline + consent: always get a refresh token, so the server can renew access itself
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    TOKEN_PATH.write_text(creds.to_json())
    print(f"Saved token to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
