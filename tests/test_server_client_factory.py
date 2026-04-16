"""
Tests for per-request client factory in src/server.py.

Validates:
- get_client_for_token: LRU caching, TTL expiration, cache eviction
- get_client_for_request: OAuth token -> per-token client, fallback to singleton
- get_client: backward-compatible alias
- Missing OPENPROJECT_API_KEY is OK when OAuth is configured
"""

import time
import pytest
from unittest.mock import patch, MagicMock
from collections import OrderedDict

from src.client import OpenProjectClient


# ---------------------------------------------------------------------------
# We cannot import src.server directly because its module-level code reads
# env vars and imports tool modules. Instead we test the functions by
# reconstructing them with controlled globals. We import the functions after
# patching the environment so the module can load.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_server_cache():
    """Clear the token cache in src.server before/after each test."""
    try:
        import src.server as srv
        srv._token_cache.clear()
    except Exception:
        pass
    yield
    try:
        import src.server as srv
        srv._token_cache.clear()
    except Exception:
        pass


@pytest.fixture
def server_module():
    """Import src.server with required env vars patched.

    Returns the module so tests can access its functions and globals.
    """
    with patch.dict("os.environ", {
        "OPENPROJECT_URL": "https://op.example.com",
        "OPENPROJECT_API_KEY": "test-api-key",
    }):
        import src.server as srv
        # Reset module state for a clean test
        srv._base_url = "https://op.example.com"
        srv._proxy = None
        srv._api_key = "test-api-key"
        srv._client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="test-api-key",
        )
        srv._token_cache.clear()
        yield srv


# ---------------------------------------------------------------------------
# get_client_for_token tests
# ---------------------------------------------------------------------------


class TestGetClientForToken:
    """Test LRU/TTL caching in get_client_for_token."""

    def test_returns_client_for_token(self, server_module):
        """Should return an OpenProjectClient configured with bearer token."""
        client = server_module.get_client_for_token("tok-aaa")
        assert isinstance(client, OpenProjectClient)
        assert client.bearer_token == "tok-aaa"
        assert client.headers["Authorization"] == "Bearer tok-aaa"

    def test_same_token_returns_same_client(self, server_module):
        """Calling with the same token twice should return the cached instance."""
        c1 = server_module.get_client_for_token("tok-aaa")
        c2 = server_module.get_client_for_token("tok-aaa")
        assert c1 is c2

    def test_different_tokens_return_different_clients(self, server_module):
        """Different tokens should yield distinct client instances."""
        c1 = server_module.get_client_for_token("tok-aaa")
        c2 = server_module.get_client_for_token("tok-bbb")
        assert c1 is not c2
        assert c1.bearer_token == "tok-aaa"
        assert c2.bearer_token == "tok-bbb"

    def test_cache_hit_does_not_create_new_client(self, server_module):
        """A cache hit should reuse the existing client, not construct a new one."""
        c1 = server_module.get_client_for_token("tok-aaa")
        with patch("src.server.OpenProjectClient") as MockClient:
            c2 = server_module.get_client_for_token("tok-aaa")
            MockClient.assert_not_called()
        assert c2 is c1

    def test_ttl_expiration_creates_new_client(self, server_module):
        """After TTL expires, a new client should be created for the same token."""
        c1 = server_module.get_client_for_token("tok-aaa")

        # Manually expire the cache entry by faking the timestamp
        server_module._token_cache["tok-aaa"] = (
            c1,
            time.monotonic() - server_module._TOKEN_CACHE_TTL - 1,
        )

        c2 = server_module.get_client_for_token("tok-aaa")
        assert c2 is not c1
        assert c2.bearer_token == "tok-aaa"

    def test_cache_eviction_when_max_exceeded(self, server_module):
        """When cache exceeds _TOKEN_CACHE_MAX, oldest entries should be evicted."""
        # Temporarily lower the max for testing
        original_max = server_module._TOKEN_CACHE_MAX
        server_module._TOKEN_CACHE_MAX = 3

        try:
            c1 = server_module.get_client_for_token("tok-1")
            c2 = server_module.get_client_for_token("tok-2")
            c3 = server_module.get_client_for_token("tok-3")
            assert len(server_module._token_cache) == 3

            # Adding a 4th should evict tok-1
            c4 = server_module.get_client_for_token("tok-4")
            assert len(server_module._token_cache) == 3
            assert "tok-1" not in server_module._token_cache
            assert "tok-4" in server_module._token_cache
        finally:
            server_module._TOKEN_CACHE_MAX = original_max

    def test_cache_lru_order_preserved(self, server_module):
        """Accessing an entry should move it to the end (most recently used)."""
        original_max = server_module._TOKEN_CACHE_MAX
        server_module._TOKEN_CACHE_MAX = 3

        try:
            server_module.get_client_for_token("tok-1")
            server_module.get_client_for_token("tok-2")
            server_module.get_client_for_token("tok-3")

            # Access tok-1 again to make it most recently used
            server_module.get_client_for_token("tok-1")

            # Adding tok-4 should evict tok-2 (the LRU), not tok-1
            server_module.get_client_for_token("tok-4")
            assert "tok-1" in server_module._token_cache
            assert "tok-2" not in server_module._token_cache
            assert "tok-3" in server_module._token_cache
            assert "tok-4" in server_module._token_cache
        finally:
            server_module._TOKEN_CACHE_MAX = original_max

    def test_client_uses_correct_base_url(self, server_module):
        """Client created by cache should use the server's _base_url."""
        client = server_module.get_client_for_token("tok-aaa")
        assert client.base_url == "https://op.example.com"

    def test_client_uses_proxy_when_set(self, server_module):
        """Client should include proxy if _proxy is set."""
        server_module._proxy = "http://proxy:8080"
        try:
            # Clear cache to force new client creation
            server_module._token_cache.clear()
            client = server_module.get_client_for_token("tok-proxy")
            assert client.proxy == "http://proxy:8080"
        finally:
            server_module._proxy = None


# ---------------------------------------------------------------------------
# get_client_for_request tests
# ---------------------------------------------------------------------------


class TestGetClientForRequest:
    """Test get_client_for_request with OAuth and API key fallback."""

    def test_uses_oauth_token_when_available(self, server_module):
        """When FastMCP provides an access token, should return a bearer client."""
        mock_token = MagicMock()
        mock_token.token = "oauth-token-xyz"

        with patch("src.server.get_access_token", return_value=mock_token):
            client = server_module.get_client_for_request()

        assert client.bearer_token == "oauth-token-xyz"
        assert client.headers["Authorization"] == "Bearer oauth-token-xyz"

    def test_falls_back_to_singleton_when_no_oauth(self, server_module):
        """When no OAuth token, should return the global API key client."""
        with patch("src.server.get_access_token", return_value=None):
            client = server_module.get_client_for_request()

        assert client is server_module._client
        assert client.api_key == "test-api-key"

    def test_raises_when_no_auth_available(self, server_module):
        """When no OAuth token and no API key client, should raise ValueError."""
        server_module._client = None

        with patch("src.server.get_access_token", return_value=None):
            with pytest.raises(ValueError, match="No authentication available"):
                server_module.get_client_for_request()

    def test_oauth_token_is_cached(self, server_module):
        """Same OAuth token should return cached client on second call."""
        mock_token = MagicMock()
        mock_token.token = "oauth-token-reuse"

        with patch("src.server.get_access_token", return_value=mock_token):
            c1 = server_module.get_client_for_request()
            c2 = server_module.get_client_for_request()

        assert c1 is c2

    def test_different_oauth_tokens_get_different_clients(self, server_module):
        """Different OAuth tokens should produce different clients."""
        tok1 = MagicMock()
        tok1.token = "user-1-token"
        tok2 = MagicMock()
        tok2.token = "user-2-token"

        with patch("src.server.get_access_token", return_value=tok1):
            c1 = server_module.get_client_for_request()
        with patch("src.server.get_access_token", return_value=tok2):
            c2 = server_module.get_client_for_request()

        assert c1 is not c2
        assert c1.bearer_token == "user-1-token"
        assert c2.bearer_token == "user-2-token"


# ---------------------------------------------------------------------------
# get_client backward compatibility
# ---------------------------------------------------------------------------


class TestGetClientAlias:
    """Test that get_client() is a backward-compatible alias."""

    def test_get_client_delegates_to_get_client_for_request(self, server_module):
        """get_client() should call get_client_for_request() and return same result."""
        with patch("src.server.get_access_token", return_value=None):
            result = server_module.get_client()
        assert result is server_module._client

    def test_get_client_with_oauth_returns_bearer_client(self, server_module):
        """get_client() should also work in OAuth mode via the alias."""
        mock_token = MagicMock()
        mock_token.token = "alias-token"

        with patch("src.server.get_access_token", return_value=mock_token):
            client = server_module.get_client()

        assert client.bearer_token == "alias-token"


# ---------------------------------------------------------------------------
# Missing API key is OK when OAuth configured
# ---------------------------------------------------------------------------


class TestMissingApiKeyOkForOAuth:
    """Missing OPENPROJECT_API_KEY should not prevent server from loading in OAuth mode."""

    def test_no_api_key_means_client_is_none(self, server_module):
        """Without API key, _client should be None but module should not error."""
        server_module._client = None
        server_module._api_key = None

        # Should not raise — OAuth mode doesn't need API key
        mock_token = MagicMock()
        mock_token.token = "oauth-only-token"

        with patch("src.server.get_access_token", return_value=mock_token):
            client = server_module.get_client_for_request()

        assert client.bearer_token == "oauth-only-token"

    def test_no_api_key_no_oauth_raises(self, server_module):
        """Without API key AND no OAuth token, should raise clear error."""
        server_module._client = None
        server_module._api_key = None

        with patch("src.server.get_access_token", return_value=None):
            with pytest.raises(ValueError, match="No authentication available"):
                server_module.get_client_for_request()
