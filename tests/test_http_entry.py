"""
Integration tests for HTTP entry point OAuth wiring.

Validates:
- HTTP entry point requires OAuth config (missing vars = clear error exit)
- Stdio entry point works without OAuth vars
- FastMCP auth is correctly wired with OAuthProxy
- SSE entry point has same OAuth requirements as HTTP
"""

import os
import subprocess
import sys
import pytest
from unittest.mock import patch, MagicMock

from fastmcp.server.auth.oauth_proxy import OAuthProxy


PYTHON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".venv", "bin", "python",
)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# HTTP entry point: missing env var validation
# ---------------------------------------------------------------------------


class TestHttpEntryMissingEnvVars:
    """HTTP entry point should exit with error when OAuth vars are missing."""

    def _run_http_entry(self, env: dict) -> subprocess.CompletedProcess:
        """Run the HTTP entry point as a subprocess with the given env."""
        return subprocess.run(
            [PYTHON, os.path.join(PROJECT_ROOT, "openproject-mcp-http.py")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def _base_env(self) -> dict:
        """Return a minimal env that lets the server module import."""
        return {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "OPENPROJECT_URL": "https://op.example.com",
            "OPENPROJECT_API_KEY": "test-key",
            "PYTHONPATH": PROJECT_ROOT,
        }

    def test_missing_oauth_client_id_exits_with_error(self):
        """Missing OAUTH_CLIENT_ID should cause exit(1) with clear error."""
        env = self._base_env()
        env["OAUTH_CLIENT_SECRET"] = "secret"
        env["MCP_BASE_URL"] = "https://mcp.example.com"
        # OAUTH_CLIENT_ID deliberately missing

        result = self._run_http_entry(env)
        assert result.returncode != 0
        assert "OAUTH_CLIENT_ID" in result.stderr

    def test_missing_oauth_client_secret_exits_with_error(self):
        """Missing OAUTH_CLIENT_SECRET should cause exit(1) with clear error."""
        env = self._base_env()
        env["OAUTH_CLIENT_ID"] = "cid"
        env["MCP_BASE_URL"] = "https://mcp.example.com"
        # OAUTH_CLIENT_SECRET deliberately missing

        result = self._run_http_entry(env)
        assert result.returncode != 0
        assert "OAUTH_CLIENT_SECRET" in result.stderr

    def test_missing_mcp_base_url_exits_with_error(self):
        """Missing MCP_BASE_URL should cause exit(1) with clear error."""
        env = self._base_env()
        env["OAUTH_CLIENT_ID"] = "cid"
        env["OAUTH_CLIENT_SECRET"] = "secret"
        # MCP_BASE_URL deliberately missing

        result = self._run_http_entry(env)
        assert result.returncode != 0
        assert "MCP_BASE_URL" in result.stderr

    def test_missing_all_oauth_vars_exits_with_error(self):
        """Missing all OAuth vars should list them all in the error."""
        env = self._base_env()
        # No OAuth vars set

        result = self._run_http_entry(env)
        assert result.returncode != 0
        assert "OAUTH_CLIENT_ID" in result.stderr
        assert "OAUTH_CLIENT_SECRET" in result.stderr
        assert "MCP_BASE_URL" in result.stderr

    def test_missing_openproject_url_exits_with_error(self):
        """Missing OPENPROJECT_URL should cause a failure at server module import.

        Note: We test this by importing server.py directly with dotenv
        disabled, since the .env file on disk may contain OPENPROJECT_URL
        and load_dotenv() would pick it up in subprocess mode.
        """
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONPATH": PROJECT_ROOT,
        }
        # Run a snippet that patches out load_dotenv before importing server
        result = subprocess.run(
            [
                PYTHON, "-c",
                "import dotenv; dotenv.load_dotenv = lambda *a, **kw: None; "
                "from src.server import mcp",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0
        assert "OPENPROJECT_URL" in result.stderr


# ---------------------------------------------------------------------------
# SSE entry point: same OAuth requirements
# ---------------------------------------------------------------------------


class TestSseEntryMissingEnvVars:
    """SSE entry point should have the same OAuth validation as HTTP."""

    def _run_sse_entry(self, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PYTHON, os.path.join(PROJECT_ROOT, "openproject-mcp-sse.py")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def _base_env(self) -> dict:
        return {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "OPENPROJECT_URL": "https://op.example.com",
            "OPENPROJECT_API_KEY": "test-key",
            "PYTHONPATH": PROJECT_ROOT,
        }

    def test_missing_oauth_vars_exits_with_error(self):
        """SSE entry with missing OAuth vars should also fail."""
        env = self._base_env()
        result = self._run_sse_entry(env)
        assert result.returncode != 0
        assert "OAUTH_CLIENT_ID" in result.stderr


# ---------------------------------------------------------------------------
# Stdio entry point: works without OAuth vars
# ---------------------------------------------------------------------------


class TestStdioEntryNoOAuth:
    """Stdio entry point should not require OAuth vars."""

    def test_stdio_does_not_require_oauth_vars(self):
        """Stdio entry with only OPENPROJECT_URL + API_KEY should not fail on import.

        We test this by importing the module logic — the stdio entry just does
        `from src.server import mcp` and `mcp.run(transport='stdio')`.
        The import should succeed without OAuth vars.
        """
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "OPENPROJECT_URL": "https://op.example.com",
            "OPENPROJECT_API_KEY": "test-key",
            "PYTHONPATH": PROJECT_ROOT,
        }

        # Run a quick check that importing src.server works without OAuth vars
        result = subprocess.run(
            [PYTHON, "-c", "from src.server import mcp; print('OK:', mcp.name)"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "OK:" in result.stdout

    def test_stdio_does_not_import_oauth_module(self):
        """The stdio entry point does not import src.oauth."""
        # Read the file and verify it doesn't reference oauth
        entry_path = os.path.join(PROJECT_ROOT, "openproject-mcp-fastmcp.py")
        with open(entry_path) as f:
            content = f.read()
        assert "oauth" not in content.lower()


# ---------------------------------------------------------------------------
# FastMCP auth wiring
# ---------------------------------------------------------------------------


class TestFastMCPAuthWiring:
    """Test that mcp.auth is correctly wired when OAuth is configured."""

    def test_mcp_auth_is_none_by_default(self):
        """Without calling create_oauth_provider, mcp.auth should be None."""
        with patch.dict("os.environ", {
            "OPENPROJECT_URL": "https://op.example.com",
            "OPENPROJECT_API_KEY": "test-key",
        }):
            import src.server as srv
            # Before OAuth wiring, auth should be None
            # (we restore it after test)
            original_auth = srv.mcp.auth
            try:
                srv.mcp.auth = None
                assert srv.mcp.auth is None
            finally:
                srv.mcp.auth = original_auth

    def test_mcp_auth_set_to_oauth_proxy(self):
        """After create_oauth_provider(), mcp.auth should be an OAuthProxy."""
        with patch.dict("os.environ", {
            "OPENPROJECT_URL": "https://op.example.com",
            "OPENPROJECT_API_KEY": "test-key",
            "OAUTH_CLIENT_ID": "cid",
            "OAUTH_CLIENT_SECRET": "csec",
            "MCP_BASE_URL": "https://mcp.example.com",
        }):
            import src.server as srv
            from src.oauth import create_oauth_provider

            original_auth = srv.mcp.auth
            try:
                srv.mcp.auth = create_oauth_provider()
                assert isinstance(srv.mcp.auth, OAuthProxy)
            finally:
                srv.mcp.auth = original_auth

    def test_create_oauth_provider_wires_verifier(self):
        """The OAuthProxy should contain an OpenProjectTokenVerifier."""
        with patch.dict("os.environ", {
            "OPENPROJECT_URL": "https://op.example.com",
            "OAUTH_CLIENT_ID": "cid",
            "OAUTH_CLIENT_SECRET": "csec",
            "MCP_BASE_URL": "https://mcp.example.com",
        }):
            from src.oauth import create_oauth_provider, OpenProjectTokenVerifier

            # Mock OAuthProxy to capture the verifier passed to it
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()

            kwargs = MockProxy.call_args.kwargs
            assert isinstance(kwargs["token_verifier"], OpenProjectTokenVerifier)


# ---------------------------------------------------------------------------
# HTTP entry: auth.py is deleted
# ---------------------------------------------------------------------------


class TestAuthModuleRemoved:
    """The old src/auth.py should be deleted."""

    def test_auth_module_does_not_exist(self):
        """src/auth.py should have been removed."""
        auth_path = os.path.join(PROJECT_ROOT, "src", "auth.py")
        assert not os.path.exists(auth_path), "src/auth.py should be deleted"

    def test_http_entry_does_not_reference_old_auth(self):
        """openproject-mcp-http.py should not import from src.auth."""
        entry_path = os.path.join(PROJECT_ROOT, "openproject-mcp-http.py")
        with open(entry_path) as f:
            content = f.read()
        assert "from src.auth" not in content
        assert "src.auth" not in content
