"""
OpenProject MCP Server - FastMCP Implementation

Main server file that initializes FastMCP and registers all tools.
"""

import os
import time
import logging
from collections import OrderedDict
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token

from src.client import OpenProjectClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(
    name="openproject-mcp"
)

# Server configuration
_base_url = os.getenv("OPENPROJECT_URL")
_proxy = os.getenv("OPENPROJECT_PROXY")

if not _base_url:
    raise ValueError("Missing required environment variable: OPENPROJECT_URL must be set")

# Initialize global client for API key mode (optional)
_client = None
_api_key = os.getenv("OPENPROJECT_API_KEY")

if _api_key:
    try:
        _client = OpenProjectClient(
            base_url=_base_url,
            api_key=_api_key,
            proxy=_proxy
        )
        logger.info(f"✅ OpenProject MCP Server initialized (API key mode)")
        logger.info(f"   Server: {_base_url}")
        logger.info(f"   Proxy: {_proxy if _proxy else 'None'}")
    except Exception as e:
        logger.error(f"❌ Failed to initialize OpenProject client: {e}")
        raise
else:
    logger.info(f"✅ OpenProject MCP Server initialized (OAuth mode)")
    logger.info(f"   Server: {_base_url}")
    logger.info(f"   Proxy: {_proxy if _proxy else 'None'}")


# --- Per-token client cache (LRU with TTL) ---

_TOKEN_CACHE_MAX = 100
_TOKEN_CACHE_TTL = 300  # 5 minutes
_token_cache: OrderedDict[str, tuple[OpenProjectClient, float]] = OrderedDict()


def get_client_for_token(token: str) -> OpenProjectClient:
    """Get or create an OpenProjectClient for a bearer token, with LRU/TTL caching."""
    now = time.monotonic()

    if token in _token_cache:
        client, created_at = _token_cache[token]
        if now - created_at < _TOKEN_CACHE_TTL:
            _token_cache.move_to_end(token)
            return client
        else:
            del _token_cache[token]

    client = OpenProjectClient(
        base_url=_base_url,
        bearer_token=token,
        proxy=_proxy,
    )

    _token_cache[token] = (client, now)
    _token_cache.move_to_end(token)

    # Evict oldest entries beyond max size
    while len(_token_cache) > _TOKEN_CACHE_MAX:
        _token_cache.popitem(last=False)

    return client


def get_client_for_request() -> OpenProjectClient:
    """Get an OpenProjectClient for the current request.

    Checks FastMCP context for an OAuth access token first,
    falls back to the global API key client.
    """
    access_token = get_access_token()
    if access_token is not None:
        return get_client_for_token(access_token.token)

    if _client is not None:
        return _client

    raise ValueError(
        "No authentication available. Set OPENPROJECT_API_KEY for API key mode "
        "or configure OAuth for token-based access."
    )


# Backward-compatible alias
def get_client() -> OpenProjectClient:
    """Get OpenProject client instance."""
    return get_client_for_request()


# Import ALL tool modules (decorators auto-register tools)
logger.info("Loading tool modules...")

try:
    # Phase 1: Priority tools (7 tools)
    from src.tools import connection      # 2 tools: test_connection, check_permissions
    from src.tools import work_packages   # 7 tools: list, create, update, delete, list_types, list_statuses, list_priorities
    from src.tools import projects        # 5 tools: list, get, create, update, delete

    # Phase 2: Additional tools (28 tools)
    from src.tools import users           # 6 tools: list_users, get_user, list_roles, get_role, list_project_members, list_user_projects
    from src.tools import memberships     # 5 tools: list, get, create, update, delete
    from src.tools import hierarchy       # 3 tools: set_parent, remove_parent, list_children
    from src.tools import relations       # 5 tools: create, list, get, update, delete
    from src.tools import time_entries    # 5 tools: list, create, update, delete, list_activities
    from src.tools import versions        # 2 tools: list, create
    from src.tools import weekly_reports   # 4 tools: generate_weekly_report, get_report_data, generate_this_week_report, generate_last_week_report
    from src.tools import news             # 5 tools: list_news, create_news, get_news, update_news, delete_news

    logger.info("✅ All 49 tool modules loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️  Some tool modules failed to import: {e}")
    raise

