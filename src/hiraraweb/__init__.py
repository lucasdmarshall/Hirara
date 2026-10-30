"""Self-hosted `web_fetch` / `web_search` tools."""

from .budget import UsageBudget
from .cache import Cache
from .config import (
    BudgetConfig,
    CacheConfig,
    FetchConfig,
    ProvenanceConfig,
    RobotsConfig,
    SearchConfig,
)
from .fetch import FetchError, FetchResult, web_fetch, web_fetch_sync
from .guard import BlockedURL, Target, check_ip, resolve_target
from .provenance import UrlRegistry, normalize_url
from .robots import RobotsCache
from .search import (
    SearchError,
    SearchProvider,
    SearchResult,
    normalize_query,
    rank_by_relevance,
    relevance_score,
    web_search,
)
from .tools import Toolset, wrap_untrusted

__all__ = [
    "BudgetConfig",
    "RobotsCache",
    "RobotsConfig",
    "UsageBudget",
    "BlockedURL",
    "BudgetConfig",
    "Cache",
    "CacheConfig",
    "FetchConfig",
    "FetchError",
    "FetchResult",
    "ProvenanceConfig",
    "SearchConfig",
    "SearchError",
    "SearchProvider",
    "SearchResult",
    "Target",
    "Toolset",
    "UrlRegistry",
    "check_ip",
    "normalize_query",
    "normalize_url",
    "rank_by_relevance",
    "relevance_score",
    "resolve_target",
    "web_fetch",
    "web_fetch_sync",
    "web_search",
    "wrap_untrusted",
]

__version__ = "0.4.0"
