"""hirara-core — shared building blocks for Hirara agent tools.

The SSRF guard lives here so every tool in the hub shares one implementation.
A tool that fetches an attacker-influenceable URL should never hand-roll its
own perimeter — that is how a new tool silently re-introduces an old hole.
"""

from .download import (
    DEFAULT_MAX_BYTES,
    DownloadError,
    DownloadResult,
    safe_download,
    safe_download_sync,
)
from .ssrf import (
    ALLOWED_PORTS,
    ALLOWED_SCHEMES,
    BlockedURL,
    Target,
    check_ip,
    resolve_target,
)

__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "BlockedURL",
    "DEFAULT_MAX_BYTES",
    "DownloadError",
    "DownloadResult",
    "Target",
    "check_ip",
    "resolve_target",
    "safe_download",
    "safe_download_sync",
]

__version__ = "0.2.0"
