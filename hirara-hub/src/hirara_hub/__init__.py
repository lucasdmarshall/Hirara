"""hirara-hub — a thin aggregating gateway for the Hirara tool hub.

One HTTP API and one MCP server that front every tool service: aggregated
/schemas, a /call forwarder, /health, and opt-in bearer-token auth. Holds no
tool dependencies — it only routes.
"""

from .config import HubConfig
from .gateway import Gateway
from .registry import TOOLS, ToolRoute, services

__all__ = ["Gateway", "HubConfig", "TOOLS", "ToolRoute", "services"]

__version__ = "0.6.0"
