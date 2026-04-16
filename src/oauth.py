"""OAuth 2.1 support for OpenProject MCP server.

Provides token verification against OpenProject's API and a factory
for building an OAuthProxy that proxies to OpenProject's OAuth endpoints.
"""

import os
import logging

import httpx
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.oauth_proxy import OAuthProxy

logger = logging.getLogger(__name__)


class OpenProjectTokenVerifier(TokenVerifier):
    """Verify bearer tokens by calling OpenProject /api/v3/users/me."""

    def __init__(
        self,
        openproject_url: str,
        required_scopes: list[str] | None = None,
    ):
        super().__init__(required_scopes=required_scopes)
        self._openproject_url = openproject_url.rstrip("/")

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._openproject_url}/api/v3/users/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code != 200:
                    logger.debug("Token verification failed: HTTP %d", resp.status_code)
                    return None

                user = resp.json()
                user_id = str(user.get("id", "unknown"))
                login = user.get("login", user_id)

                return AccessToken(
                    token=token,
                    client_id=login,
                    scopes=self.required_scopes or [],
                    expires_at=None,
                )
        except httpx.RequestError as e:
            logger.debug("Token verification request failed: %s", e)
            return None
        except Exception as e:
            logger.debug("Token verification error: %s", e)
            return None


def create_oauth_provider() -> OAuthProxy:
    """Build an OAuthProxy for OpenProject from environment variables.

    Required env vars:
        OPENPROJECT_URL: Base URL of OpenProject instance
        OAUTH_CLIENT_ID: OAuth app client ID registered in OpenProject
        OAUTH_CLIENT_SECRET: OAuth app client secret
        MCP_BASE_URL: Public URL where this MCP server is reachable

    Returns:
        Configured OAuthProxy instance.
    """
    op_url = os.environ["OPENPROJECT_URL"].rstrip("/")
    client_id = os.environ["OAUTH_CLIENT_ID"]
    client_secret = os.environ["OAUTH_CLIENT_SECRET"]
    mcp_base_url = os.environ["MCP_BASE_URL"]

    verifier = OpenProjectTokenVerifier(openproject_url=op_url)

    return OAuthProxy(
        upstream_authorization_endpoint=f"{op_url}/oauth/authorize",
        upstream_token_endpoint=f"{op_url}/oauth/token",
        upstream_client_id=client_id,
        upstream_client_secret=client_secret,
        token_verifier=verifier,
        base_url=mcp_base_url,
        require_authorization_consent="external",
    )
