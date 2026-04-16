"""
Tests for OpenProjectClient bearer token support.

Validates that the client correctly handles:
- api_key mode (Basic Auth, backward compatibility)
- bearer_token mode (OAuth Bearer token)
- Validation: rejects both or neither credential
- _encode_api_key not called in bearer mode
"""

import base64
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import aiohttp

from src.client import OpenProjectClient


# ---------------------------------------------------------------------------
# Construction / validation tests
# ---------------------------------------------------------------------------


class TestClientConstruction:
    """Test OpenProjectClient __init__ validation and header setup."""

    def test_api_key_mode_sets_basic_auth_header(self):
        """api_key mode should set Authorization: Basic <encoded>."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="test-key-123",
        )
        assert client.api_key == "test-key-123"
        assert client.bearer_token is None

        expected_encoded = base64.b64encode(b"apikey:test-key-123").decode()
        assert client.headers["Authorization"] == f"Basic {expected_encoded}"

    def test_bearer_token_mode_sets_bearer_header(self):
        """bearer_token mode should set Authorization: Bearer <token>."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            bearer_token="oauth-token-abc",
        )
        assert client.bearer_token == "oauth-token-abc"
        assert client.api_key is None
        assert client.headers["Authorization"] == "Bearer oauth-token-abc"

    def test_rejects_both_api_key_and_bearer_token(self):
        """Providing both api_key and bearer_token should raise ValueError."""
        with pytest.raises(ValueError, match="not both"):
            OpenProjectClient(
                base_url="https://op.example.com",
                api_key="key",
                bearer_token="token",
            )

    def test_rejects_neither_api_key_nor_bearer_token(self):
        """Providing neither credential should raise ValueError."""
        with pytest.raises(ValueError, match="required"):
            OpenProjectClient(
                base_url="https://op.example.com",
            )

    def test_base_url_trailing_slash_stripped(self):
        """base_url should have trailing slash removed."""
        client = OpenProjectClient(
            base_url="https://op.example.com/",
            api_key="k",
        )
        assert client.base_url == "https://op.example.com"

    def test_proxy_stored(self):
        """proxy parameter should be stored."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="k",
            proxy="http://proxy:8080",
        )
        assert client.proxy == "http://proxy:8080"

    def test_common_headers_present_in_api_key_mode(self):
        """Content-Type, Accept, User-Agent headers should be set in api_key mode."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="k",
        )
        assert client.headers["Content-Type"] == "application/json"
        assert client.headers["Accept"] == "application/json"
        assert "OpenProject-MCP" in client.headers["User-Agent"]

    def test_common_headers_present_in_bearer_mode(self):
        """Content-Type, Accept, User-Agent headers should be set in bearer mode."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            bearer_token="tok",
        )
        assert client.headers["Content-Type"] == "application/json"
        assert client.headers["Accept"] == "application/json"
        assert "OpenProject-MCP" in client.headers["User-Agent"]


# ---------------------------------------------------------------------------
# _encode_api_key tests
# ---------------------------------------------------------------------------


class TestEncodeApiKey:
    """Verify _encode_api_key behaviour and its non-use in bearer mode."""

    def test_encode_api_key_produces_correct_base64(self):
        """_encode_api_key should base64-encode 'apikey:<key>'."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="my-secret",
        )
        result = client._encode_api_key()
        decoded = base64.b64decode(result).decode()
        assert decoded == "apikey:my-secret"

    def test_encode_api_key_not_called_in_bearer_mode(self):
        """In bearer_token mode, _encode_api_key should never be invoked."""
        with patch.object(
            OpenProjectClient, "_encode_api_key", side_effect=AssertionError("should not be called")
        ):
            # This should succeed without calling _encode_api_key
            client = OpenProjectClient(
                base_url="https://op.example.com",
                bearer_token="tok",
            )
            assert client.headers["Authorization"] == "Bearer tok"


# ---------------------------------------------------------------------------
# _request tests (verifying headers are sent correctly)
# ---------------------------------------------------------------------------


class TestRequestHeaders:
    """Test that _request sends the correct auth header to the API."""

    @pytest.mark.asyncio
    async def test_api_key_request_sends_basic_auth(self):
        """Requests in api_key mode should carry the Basic auth header."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="test-key",
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value='{"_type": "Root"}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client._request("GET", "/test")

        # Verify the request was called with Basic auth header
        call_kwargs = mock_session.request.call_args
        headers_sent = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        expected_encoded = base64.b64encode(b"apikey:test-key").decode()
        assert headers_sent["Authorization"] == f"Basic {expected_encoded}"

    @pytest.mark.asyncio
    async def test_bearer_request_sends_bearer_auth(self):
        """Requests in bearer mode should carry the Bearer auth header."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            bearer_token="my-oauth-token",
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value='{"_type": "Root"}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client._request("GET", "/test")

        call_kwargs = mock_session.request.call_args
        headers_sent = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers_sent["Authorization"] == "Bearer my-oauth-token"

    @pytest.mark.asyncio
    async def test_request_builds_correct_url(self):
        """_request should combine base_url + /api/v3 + endpoint."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="k",
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value='{}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await client._request("GET", "/projects")

        call_kwargs = mock_session.request.call_args
        url_sent = call_kwargs.kwargs.get("url") or call_kwargs[1].get("url")
        assert url_sent == "https://op.example.com/api/v3/projects"


# ---------------------------------------------------------------------------
# SSL verification tests
# ---------------------------------------------------------------------------


class TestSSLVerification:
    """Test SSL verification configuration."""

    def test_ssl_verify_defaults_to_true(self):
        """By default, verify_ssl should be True."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="k",
        )
        assert client.verify_ssl is True

    @patch.dict("os.environ", {"OPENPROJECT_VERIFY_SSL": "false"})
    def test_ssl_verify_can_be_disabled(self):
        """Setting OPENPROJECT_VERIFY_SSL=false should disable verification."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="k",
        )
        assert client.verify_ssl is False

    @patch.dict("os.environ", {"OPENPROJECT_VERIFY_SSL": "true"})
    def test_ssl_verify_explicit_true(self):
        """Setting OPENPROJECT_VERIFY_SSL=true should keep verification enabled."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            api_key="k",
        )
        assert client.verify_ssl is True


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test _request error handling paths."""

    @pytest.mark.asyncio
    async def test_api_error_raises_with_status(self):
        """HTTP 4xx/5xx should raise an exception with status info."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            bearer_token="tok",
        )

        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value='{"message":"Unauthorized"}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception, match="401"):
                await client._request("GET", "/test")

    @pytest.mark.asyncio
    async def test_api_error_in_bearer_mode_raises(self):
        """Bearer mode 403 errors should also raise properly."""
        client = OpenProjectClient(
            base_url="https://op.example.com",
            bearer_token="expired-token",
        )

        mock_response = AsyncMock()
        mock_response.status = 403
        mock_response.text = AsyncMock(return_value='{"message":"Forbidden"}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception, match="403"):
                await client._request("GET", "/test")
