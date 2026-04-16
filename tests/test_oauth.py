"""
Tests for OAuth 2.1 support in src/oauth.py.

Validates:
- OpenProjectTokenVerifier: verify_token with valid/invalid tokens
- create_oauth_provider: returns correctly configured OAuthProxy
- Environment variable validation: missing vars raise clear errors
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call
import httpx

from src.oauth import OpenProjectTokenVerifier, create_oauth_provider
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.oauth_proxy import OAuthProxy


# ---------------------------------------------------------------------------
# OpenProjectTokenVerifier tests
# ---------------------------------------------------------------------------


class TestTokenVerifierInit:
    """Test OpenProjectTokenVerifier construction."""

    def test_stores_url_stripped(self):
        """URL should have trailing slash removed."""
        v = OpenProjectTokenVerifier(openproject_url="https://op.example.com/")
        assert v._openproject_url == "https://op.example.com"

    def test_stores_url_without_trailing_slash(self):
        """URL without trailing slash should be stored as-is."""
        v = OpenProjectTokenVerifier(openproject_url="https://op.example.com")
        assert v._openproject_url == "https://op.example.com"

    def test_default_required_scopes_is_empty_list(self):
        """By default, required_scopes should be [] (TokenVerifier base class coerces None)."""
        v = OpenProjectTokenVerifier(openproject_url="https://op.example.com")
        assert v.required_scopes == []

    def test_custom_required_scopes(self):
        """Custom scopes should be stored."""
        v = OpenProjectTokenVerifier(
            openproject_url="https://op.example.com",
            required_scopes=["api_v3"],
        )
        assert v.required_scopes == ["api_v3"]


class TestTokenVerifierVerifyToken:
    """Test verify_token with mocked HTTP responses."""

    @pytest.fixture
    def verifier(self):
        return OpenProjectTokenVerifier(openproject_url="https://op.example.com")

    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self, verifier):
        """A 200 response with user data should return an AccessToken."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 42,
            "login": "jdoe",
            "firstName": "John",
            "lastName": "Doe",
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("valid-token-abc")

        assert result is not None
        assert isinstance(result, AccessToken)
        assert result.token == "valid-token-abc"
        assert result.client_id == "jdoe"
        assert result.scopes == []
        assert result.expires_at is None

    @pytest.mark.asyncio
    async def test_valid_token_sends_bearer_header(self, verifier):
        """verify_token should send Authorization: Bearer <token> to /api/v3/users/me."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "login": "admin"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            await verifier.verify_token("my-token")

        mock_client.get.assert_called_once_with(
            "https://op.example.com/api/v3/users/me",
            headers={"Authorization": "Bearer my-token"},
        )

    @pytest.mark.asyncio
    async def test_valid_token_uses_id_when_login_missing(self, verifier):
        """If 'login' is missing from response, client_id should fall back to str(id)."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 99}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("tok")

        assert result.client_id == "99"

    @pytest.mark.asyncio
    async def test_valid_token_uses_unknown_when_id_and_login_missing(self, verifier):
        """If both 'login' and 'id' are missing, client_id should be 'unknown'."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("tok")

        assert result.client_id == "unknown"

    @pytest.mark.asyncio
    async def test_valid_token_with_required_scopes(self):
        """When required_scopes are set, they should be included in AccessToken."""
        verifier = OpenProjectTokenVerifier(
            openproject_url="https://op.example.com",
            required_scopes=["api_v3", "read"],
        )

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "login": "admin"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("tok")

        assert result.scopes == ["api_v3", "read"]

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none_on_401(self, verifier):
        """A 401 response should return None."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("bad-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none_on_403(self, verifier):
        """A 403 response should return None."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("forbidden-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none_on_500(self, verifier):
        """A 500 response should return None (server error)."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("tok")

        assert result is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self, verifier):
        """A network error (httpx.RequestError) should return None, not raise."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("tok")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error_returns_none(self, verifier):
        """A timeout should return None, not raise."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            side_effect=httpx.ReadTimeout("Read timed out")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("tok")

        assert result is None


# ---------------------------------------------------------------------------
# create_oauth_provider tests
# ---------------------------------------------------------------------------


class TestCreateOAuthProvider:
    """Test create_oauth_provider factory function.

    Since OAuthProxy does not expose constructor args as public attributes,
    we mock the OAuthProxy constructor to verify it's called with the
    correct arguments.
    """

    REQUIRED_ENV = {
        "OPENPROJECT_URL": "https://op.example.com",
        "OAUTH_CLIENT_ID": "my-client-id",
        "OAUTH_CLIENT_SECRET": "my-client-secret",
        "MCP_BASE_URL": "https://mcp.example.com",
    }

    def test_returns_oauth_proxy_instance(self):
        """Should return an OAuthProxy instance."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            result = create_oauth_provider()
        assert isinstance(result, OAuthProxy)

    def test_passes_correct_authorization_endpoint(self):
        """Should pass /oauth/authorize as upstream_authorization_endpoint."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        assert kwargs["upstream_authorization_endpoint"] == "https://op.example.com/oauth/authorize"

    def test_passes_correct_token_endpoint(self):
        """Should pass /oauth/token as upstream_token_endpoint."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        assert kwargs["upstream_token_endpoint"] == "https://op.example.com/oauth/token"

    def test_passes_correct_client_id(self):
        """Should pass OAUTH_CLIENT_ID as upstream_client_id."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        assert kwargs["upstream_client_id"] == "my-client-id"

    def test_passes_correct_client_secret(self):
        """Should pass OAUTH_CLIENT_SECRET as upstream_client_secret."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        assert kwargs["upstream_client_secret"] == "my-client-secret"

    def test_passes_openproject_token_verifier(self):
        """Should pass an OpenProjectTokenVerifier as token_verifier."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        verifier = kwargs["token_verifier"]
        assert isinstance(verifier, OpenProjectTokenVerifier)
        assert verifier._openproject_url == "https://op.example.com"

    def test_passes_correct_base_url(self):
        """Should pass MCP_BASE_URL as base_url."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        assert kwargs["base_url"] == "https://mcp.example.com"

    def test_passes_require_authorization_consent_external(self):
        """Should set require_authorization_consent='external'."""
        with patch.dict("os.environ", self.REQUIRED_ENV, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        assert kwargs["require_authorization_consent"] == "external"

    def test_url_trailing_slash_stripped_in_endpoints(self):
        """OPENPROJECT_URL trailing slash should be stripped in OAuth endpoints."""
        env = dict(self.REQUIRED_ENV)
        env["OPENPROJECT_URL"] = "https://op.example.com/"
        with patch.dict("os.environ", env, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        assert kwargs["upstream_authorization_endpoint"] == "https://op.example.com/oauth/authorize"
        assert kwargs["upstream_token_endpoint"] == "https://op.example.com/oauth/token"

    def test_verifier_url_matches_stripped_openproject_url(self):
        """Verifier should use the stripped OPENPROJECT_URL."""
        env = dict(self.REQUIRED_ENV)
        env["OPENPROJECT_URL"] = "https://op.example.com/"
        with patch.dict("os.environ", env, clear=False):
            with patch("src.oauth.OAuthProxy") as MockProxy:
                create_oauth_provider()
        kwargs = MockProxy.call_args.kwargs
        verifier = kwargs["token_verifier"]
        assert verifier._openproject_url == "https://op.example.com"


# ---------------------------------------------------------------------------
# Environment variable validation
# ---------------------------------------------------------------------------


class TestCreateOAuthProviderEnvValidation:
    """Test that missing env vars raise clear errors."""

    BASE_ENV = {
        "OPENPROJECT_URL": "https://op.example.com",
        "OAUTH_CLIENT_ID": "cid",
        "OAUTH_CLIENT_SECRET": "csec",
        "MCP_BASE_URL": "https://mcp.example.com",
    }

    def test_missing_openproject_url_raises(self):
        """Missing OPENPROJECT_URL should raise KeyError."""
        env = dict(self.BASE_ENV)
        del env["OPENPROJECT_URL"]
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(KeyError, match="OPENPROJECT_URL"):
                create_oauth_provider()

    def test_missing_oauth_client_id_raises(self):
        """Missing OAUTH_CLIENT_ID should raise KeyError."""
        env = dict(self.BASE_ENV)
        del env["OAUTH_CLIENT_ID"]
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(KeyError, match="OAUTH_CLIENT_ID"):
                create_oauth_provider()

    def test_missing_oauth_client_secret_raises(self):
        """Missing OAUTH_CLIENT_SECRET should raise KeyError."""
        env = dict(self.BASE_ENV)
        del env["OAUTH_CLIENT_SECRET"]
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(KeyError, match="OAUTH_CLIENT_SECRET"):
                create_oauth_provider()

    def test_missing_mcp_base_url_raises(self):
        """Missing MCP_BASE_URL should raise KeyError."""
        env = dict(self.BASE_ENV)
        del env["MCP_BASE_URL"]
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(KeyError, match="MCP_BASE_URL"):
                create_oauth_provider()
