# OpenProject MCP Server — Installation Guide

This guide walks through running the OpenProject MCP server in Docker and connecting it to the Claude Code CLI.

---

## Prerequisites

- macOS (instructions below assume macOS; Linux equivalents are straightforward)
- [Claude Code CLI](https://claude.ai/code) installed
- An OpenProject instance you can log into

---

## 1. Install Docker on macOS

### Option A — Docker Desktop (recommended for most users)

1. Download Docker Desktop from [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
2. Open the downloaded `.dmg` and drag Docker to `/Applications`
3. Launch Docker Desktop from your Applications folder and follow the setup wizard
4. Verify the installation:

```bash
docker --version
docker compose version
```

### Option B — OrbStack (lighter alternative)

[OrbStack](https://orbstack.dev) is a faster, lighter alternative to Docker Desktop on macOS:

```bash
brew install orbstack
```

---

## 2. Get an API Token from OpenProject

1. Log in to your OpenProject instance
2. Click your **avatar** in the top-right corner
3. Go to **My account** → **Access tokens**
4. Click **+ API token**
5. Give it a name (e.g. `claude-mcp`) and click **Create**
6. **Copy the token immediately** — it will not be shown again

---

## 3. Create a Working Directory and Configuration

Create a dedicated directory anywhere on your machine:

```bash
mkdir openproject-mcp && cd openproject-mcp
```

### Create the `docker-compose.yml`

```bash
cat > docker-compose.yml << 'EOF'
services:
  openproject-mcp:
    image: glab.backend.spamhaus:5100/resources/ai/openproject-mcp-server/main:1774436840
    container_name: openproject-mcp
    restart: unless-stopped
    environment:
      OPENPROJECT_URL: "${OPENPROJECT_URL}"
      OPENPROJECT_API_KEY: "${OPENPROJECT_API_KEY}"
      OPENPROJECT_PROXY: "${OPENPROJECT_PROXY:-}"
      OPENPROJECT_VERIFY_SSL: "${OPENPROJECT_VERIFY_SSL:-true}"
      LOG_LEVEL: "${LOG_LEVEL:-INFO}"
      PYTHONPATH: "/app"
      MCP_HOST: "${MCP_HOST:-0.0.0.0}"
      MCP_PORT: "${MCP_PORT:-8000}"
    ports:
      - "${MCP_PORT:-8000}:${MCP_PORT:-8000}"
EOF
```

> To upgrade to a newer release, check the available tags at:
> `https://glab.backend.spamhaus/resources/ai/openproject-mcp-server/container_registry/244`
> and replace the tag in `docker-compose.yml` with the latest one listed there.

### Create the startup script

```bash
cat > start-mcp.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

# --- OpenProject configuration ---
# Edit these values to match your environment

export OPENPROJECT_URL="https://openproject.backend.spamhaus"
export OPENPROJECT_API_KEY="paste-your-api-token-here"

# Our OpenProject uses a self-signed certificate:
export OPENPROJECT_VERIFY_SSL="false"

# Uncomment if you need an HTTP proxy:
# export OPENPROJECT_PROXY="http://proxy.example.com:8080"

# --- Server configuration (defaults are fine for most setups) ---
export MCP_HOST="0.0.0.0"
export MCP_PORT="8000"
export LOG_LEVEL="INFO"

# --- Start the container ---
docker compose up -d
echo "MCP server started on http://localhost:${MCP_PORT}"
EOF

chmod +x start-mcp.sh
```

Edit `start-mcp.sh` and fill in your `OPENPROJECT_URL` and `OPENPROJECT_API_KEY`.

> **Security note:** `start-mcp.sh` contains your API token. Do not commit it to version control or share it.

---

## 4. Start the Server

```bash
./start-mcp.sh
```

### Stop the server

```bash
docker compose down
```

### After a reboot

The container is configured with `restart: unless-stopped`, which means Docker will restart it automatically when the Docker daemon starts — but only if the container was still running when you last shut down your machine.

If you stopped it manually with `docker compose down` before rebooting, run `./start-mcp.sh` again after the reboot.

You can also start, stop, and monitor the container visually from the **Docker Desktop** or **OrbStack** app — look for the container named `openproject-mcp` in the container list. No terminal needed.

### View logs

```bash
docker compose logs -f openproject-mcp
```

---

## 5. Connect Claude Code CLI

Once the container is running, register the MCP server with Claude Code:

```bash
claude mcp add --transport http openproject http://localhost:8000/mcp
```

Verify it is registered:

```bash
claude mcp list
```

### Reconnect after a restart

If you restart the container, Claude Code will reconnect automatically on the next session.
To reconnect manually inside an active session, type `/mcp` in the Claude Code prompt.

---

## 6. Verify the Connection

Inside a Claude Code session, ask:

> "Test the connection to OpenProject"

or

> "List my work packages"

Claude will call the MCP server and return results from your OpenProject instance.

---

## Environment Variable Reference

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OPENPROJECT_URL` | Yes | URL of your OpenProject instance | — |
| `OPENPROJECT_API_KEY` | Yes | API token from your OpenProject profile | — |
| `OPENPROJECT_PROXY` | No | HTTP proxy URL | _(none)_ |
| `OPENPROJECT_VERIFY_SSL` | No | Set to `false` for self-signed certificates | `true` |
| `MCP_HOST` | No | Interface to bind to (`0.0.0.0` for Docker) | `0.0.0.0` |
| `MCP_PORT` | No | Port the server listens on | `8000` |
| `LOG_LEVEL` | No | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

---

## Troubleshooting

**Container fails to start**
```bash
docker compose logs openproject-mcp
```
Check that `OPENPROJECT_URL` and `OPENPROJECT_API_KEY` are set correctly in `start-mcp.sh`.

**Claude Code cannot connect**
Verify the container is running and the port is bound:
```bash
docker compose ps
# Should show: 0.0.0.0:8000->8000/tcp
```

**SSL certificate errors**
If your OpenProject instance uses a self-signed or internal CA certificate, uncomment this line in `start-mcp.sh`:
```bash
export OPENPROJECT_VERIFY_SSL="false"
```
The server will log a warning at startup when SSL verification is disabled.

**Re-register the MCP server**
```bash
claude mcp remove openproject
claude mcp add --transport http openproject http://localhost:8000/mcp
```
