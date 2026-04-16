# How to Test OAuth 2.1 Multi-User Mode

This guide walks you through testing the OAuth multi-user MCP server
using docker-compose and `.env`.

## Prerequisites

- Docker + docker-compose
- Admin access to your OpenProject instance
- The `feat/oauth-multiuser` branch checked out

---

## Step 1: Register an OAuth Application in OpenProject

1. Log into OpenProject as an **administrator**
2. Go to **Administration > Authentication > OAuth applications**
3. Click **New OAuth application**
4. Fill in:
   - **Name**: `MCP Server` (or any label)
   - **Redirect URI**: `http://localhost:8000/auth/callback`
     (adjust host/port if you changed `MCP_HOST`/`MCP_PORT`)
   - **Scopes**: check `api_v3`
   - **Confidential**: Yes
5. Click **Create**
6. Note the **Client ID** and **Client Secret** shown on the next page

> If your MCP server will be accessed from a different host (not localhost),
> use that host in the redirect URI. The URI must match exactly.

---

## Step 2: Update `.env`

Add the OAuth variables to your existing `.env` file:

```env
# OpenProject Configuration (existing)
OPENPROJECT_URL=https://openproject.backend.spamhaus
OPENPROJECT_VERIFY_SSL=false
LOG_LEVEL=DEBUG

# --- OAuth 2.1 (NEW) ---
# Paste the Client ID and Secret from Step 1
OAUTH_CLIENT_ID=your-client-id-from-openproject
OAUTH_CLIENT_SECRET=your-client-secret-from-openproject

# Public URL where the MCP server is reachable.
# Must match the redirect URI base registered in OpenProject.
MCP_BASE_URL=http://localhost:8000

# --- Optional (existing) ---
OPENPROJECT_PROXY=
MCP_HOST=0.0.0.0
MCP_PORT=8000
```

> **Note**: `OPENPROJECT_API_KEY` is no longer required for OAuth mode.
> You can keep it in `.env` for fallback/stdio use, but it won't be used
> by the HTTP entry point. If you remove it, make sure you don't try to
> run the stdio entry point without it.

---

## Step 3: Update `requirements.txt`

The OAuth module needs two new dependencies. Add them:

```
httpx>=0.28.0
cryptography>=42.0.0
```

Your full `requirements.txt` should look like:

```
fastmcp>=2.0.0
mcp>=1.0.0
aiohttp>=3.8.0
python-dotenv>=1.0.0
certifi>=2022.0.0
pydantic>=2.0.0
uvicorn>=0.24.0
starlette>=0.27.0
httpx>=0.28.0
cryptography>=42.0.0
```

---

## Step 4: Update `docker-compose.yml`

The docker-compose needs the new OAuth env vars passed through:

```yaml
services:
  openproject-mcp:
    build:
      context: .
      dockerfile: Dockerfile
    image: openproject-mcp-server:local
    container_name: openproject-mcp
    restart: unless-stopped
    command: ["python", "openproject-mcp-http.py"]
    environment:
      OPENPROJECT_URL: "${OPENPROJECT_URL}"
      OPENPROJECT_PROXY: "${OPENPROJECT_PROXY:-}"
      OPENPROJECT_VERIFY_SSL: "${OPENPROJECT_VERIFY_SSL:-true}"
      LOG_LEVEL: "${LOG_LEVEL:-INFO}"
      PYTHONPATH: "/app"
      MCP_HOST: "${MCP_HOST:-0.0.0.0}"
      MCP_PORT: "${MCP_PORT:-8000}"
      # OAuth 2.1 (required for HTTP mode)
      OAUTH_CLIENT_ID: "${OAUTH_CLIENT_ID}"
      OAUTH_CLIENT_SECRET: "${OAUTH_CLIENT_SECRET}"
      MCP_BASE_URL: "${MCP_BASE_URL}"
    ports:
      - "${MCP_PORT:-8000}:${MCP_PORT:-8000}"
```

Key changes from the original:
- **`command`**: changed from `openproject-mcp-sse.py` to `openproject-mcp-http.py`
- **Added**: `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `MCP_BASE_URL`
- **Removed**: `OPENPROJECT_API_KEY` (not needed in OAuth mode)
- **Removed**: `TEST_CONNECTION_ON_STARTUP` (not applicable without a static API key)

---

## Step 5: Build and Run

```bash
# Rebuild the image (picks up new deps + code)
docker-compose build --no-cache

# Start the server
docker-compose up
```

You should see output like:

```
Starting OpenProject MCP Server (HTTP + OAuth)
   Host: 0.0.0.0
   Port: 8000
   OpenProject: https://openproject.backend.spamhaus
```

If you see an error about missing `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`,
or `MCP_BASE_URL`, check your `.env` file.

---

## Step 6: Verify the Server is Running

Check that the OAuth metadata endpoints respond:

```bash
# Protected resource metadata (RFC 9728)
curl -s http://localhost:8000/.well-known/oauth-protected-resource | python3 -m json.tool

# Authorization server metadata (RFC 8414)
curl -s http://localhost:8000/.well-known/oauth-authorization-server | python3 -m json.tool
```

Both should return JSON with endpoint URLs. If they do, the server is up
and OAuth is wired correctly.

---

## Step 7: Test the Full OAuth Flow

### Option A: Using MCP Inspector

MCP Inspector is the easiest way to test interactively:

```bash
npx @anthropics/mcp-inspector
```

1. Set the server URL to `http://localhost:8000/mcp`
2. Set transport to `HTTP`
3. The inspector should trigger the OAuth flow automatically
4. You'll be redirected to your OpenProject login page
5. Log in and authorize the MCP Server application
6. After redirect, you should be able to call tools
7. Try `test_connection` — it should show your user identity
8. Try `check_permissions` — should show YOUR user, not a service account

### Option B: Manual curl flow

This is more verbose but useful for debugging.

```bash
# 1. Dynamic Client Registration
curl -s -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "test-client",
    "redirect_uris": ["http://localhost:3000/callback"],
    "grant_types": ["authorization_code"],
    "response_types": ["code"]
  }' | python3 -m json.tool

# Note the client_id and client_secret from the response

# 2. Generate a PKCE code verifier and challenge
CODE_VERIFIER=$(openssl rand -base64 32 | tr -d '=+/' | head -c 43)
CODE_CHALLENGE=$(echo -n "$CODE_VERIFIER" | openssl dgst -sha256 -binary | base64 | tr -d '=' | tr '+/' '-_')

# 3. Open this URL in your browser to authorize:
echo "http://localhost:8000/authorize?response_type=code&client_id=<CLIENT_ID>&redirect_uri=http://localhost:3000/callback&code_challenge=$CODE_CHALLENGE&code_challenge_method=S256&scope=api_v3"

# 4. After login + authorize, you'll be redirected to
#    http://localhost:3000/callback?code=<AUTH_CODE>
#    Copy the code parameter

# 5. Exchange the code for a token
curl -s -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code&code=<AUTH_CODE>&client_id=<CLIENT_ID>&redirect_uri=http://localhost:3000/callback&code_verifier=$CODE_VERIFIER" \
  | python3 -m json.tool

# Note the access_token from the response

# 6. Call a tool with the token
curl -s -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/call", "id": 1, "params": {"name": "check_permissions"}}' \
  | python3 -m json.tool
```

The response to `check_permissions` should show the identity of the
OpenProject user who authorized the OAuth app — not a service account.

### Option C: Using Claude Code (CLI)

**Important**: You must use `http` transport (not `sse`). The MCP endpoint
is `/mcp`.

```bash
claude mcp add --transport http openproject http://localhost:8000/mcp
```

This registers the MCP server. On first use, Claude Code will:
1. Open a browser window for OpenProject login
2. After authorization, the MCP connection is established automatically
3. Ask Claude: "Test my OpenProject connection" — it should call
   `test_connection` and show your user identity

To verify the connection:
```bash
claude mcp list
```

You should see `openproject` with status `connected`.

> **Do NOT use `--transport sse`**. The server uses streamable HTTP,
> not SSE. Using `sse` transport will cause `GET /mcp → 400` errors
> because the SSE client sends GET-first while the streamable HTTP
> server expects POST-first (Initialize).

### Option D: Using Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "openproject": {
      "url": "http://localhost:8000/mcp",
      "transport": "http"
    }
  }
}
```

Claude Desktop should handle the OAuth flow automatically:
1. On first connection, it opens a browser window for OP login
2. After authorization, the MCP connection is established
3. Ask Claude: "Test my OpenProject connection" — it should call
   `test_connection` and show your user identity

---

## Multi-User Verification

To confirm that different users get different identities:

1. In one browser, complete the OAuth flow as **User A**
2. Call `check_permissions` — note the returned user name
3. In a different browser (or incognito), complete the OAuth flow as **User B**
4. Call `check_permissions` — should show User B's identity, not User A's

Both users are talking to the same MCP server instance, but each
operates with their own OpenProject permissions.

---

## Troubleshooting

### Server won't start: "Missing required environment variables"
Check that `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, and `MCP_BASE_URL`
are all set in `.env` and passed through in `docker-compose.yml`.

### OAuth redirect fails: "redirect_uri mismatch"
The redirect URI registered in OpenProject must **exactly** match
`MCP_BASE_URL` + `/auth/callback`. Check for trailing slashes,
http vs https, and port numbers.

### Token verification fails: SSL errors
If your OpenProject uses a self-signed certificate, set
`OPENPROJECT_VERIFY_SSL=false` in your `.env`. This disables SSL
verification for both the OpenProject API client and the OAuth token
exchange (OAuthProxy uses httpx internally).

### `GET /mcp → 400 Bad Request` after successful authentication
You are using the wrong transport type. The server uses **streamable HTTP**,
not SSE. Reconfigure your MCP client:

```bash
# Wrong (SSE transport):
claude mcp add --transport sse openproject http://localhost:8000/mcp

# Correct (HTTP transport):
claude mcp add --transport http openproject http://localhost:8000/mcp
```

If already configured, remove and re-add:
```bash
claude mcp remove openproject
claude mcp add --transport http openproject http://localhost:8000/mcp
```

### "No authentication available" error when calling tools
This means `get_client_for_request()` found no OAuth token and no API key
fallback. Check that the OAuth flow completed successfully and the token
is being sent in the `Authorization` header.

### Tools return wrong user identity
If `check_permissions` shows a service account instead of the OAuth user,
the server may be falling back to `OPENPROJECT_API_KEY`. Make sure that
variable is NOT set in the HTTP mode environment.

---

## Switching Back to API Key Mode (stdio)

The stdio entry point is unchanged. To run single-user mode:

```bash
# Make sure OPENPROJECT_API_KEY is set in .env
docker-compose run --rm openproject-mcp python openproject-mcp-fastmcp.py
```

Or locally without Docker:

```bash
OPENPROJECT_URL=https://... OPENPROJECT_API_KEY=... python openproject-mcp-fastmcp.py
```
