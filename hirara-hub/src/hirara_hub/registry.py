"""The tool registry — which backend service serves which tool.

A tool names a *service*; the service's base URL is resolved from config (env),
so the same registry works whether the backends are localhost processes or
compose service names. The gateway never imports a tool's heavy dependencies —
it only knows where to forward.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default loopback ports for each backend service (matches each package's compose).
DEFAULT_PORTS: dict[str, int] = {
    "websearch": 8000,
    "hirarastt": 8100,
    "hirarapdf": 8200,
    "hiraracode": 8300,
    "hiraraocr": 8400,
    "hirarareader": 8500,
    "hiraranet": 8600,
    "hirarabrowser": 8700,
    "hirarahttp": 8800,
    "hirarafs": 8900,
}


@dataclass(frozen=True)
class ToolRoute:
    """Where a tool call is forwarded, and its /schemas source."""

    tool: str
    service: str
    path: str
    experimental: bool = False


# tool name -> route. Multiple tools can share one service (it exposes them all
# via its own /schemas), which is why schema aggregation is per *service*.
TOOLS: dict[str, ToolRoute] = {
    "web_search": ToolRoute("web_search", "websearch", "/web_search"),
    "web_fetch": ToolRoute("web_fetch", "websearch", "/web_fetch"),
    "transcribe": ToolRoute("transcribe", "hirarastt", "/transcribe", experimental=True),
    "pdf_read": ToolRoute("pdf_read", "hirarapdf", "/pdf_read"),
    "pdf_info": ToolRoute("pdf_info", "hirarapdf", "/pdf_info"),
    "pdf_create": ToolRoute("pdf_create", "hirarapdf", "/pdf_create"),
    "execute_code": ToolRoute("execute_code", "hiraracode", "/execute_code"),
    "ocr_read": ToolRoute("ocr_read", "hiraraocr", "/ocr_read"),
    "form_extract": ToolRoute("form_extract", "hiraraocr", "/form_extract"),
    "office_read": ToolRoute("office_read", "hirarareader", "/office_read"),
    "dns_lookup": ToolRoute("dns_lookup", "hiraranet", "/dns_lookup"),
    "port_scan": ToolRoute("port_scan", "hiraranet", "/port_scan"),
    "service_enum": ToolRoute("service_enum", "hiraranet", "/service_enum"),
    "browser_open": ToolRoute("browser_open", "hirarabrowser", "/browser_open"),
    "browser_click": ToolRoute("browser_click", "hirarabrowser", "/browser_click"),
    "browser_type": ToolRoute("browser_type", "hirarabrowser", "/browser_type"),
    "browser_screenshot": ToolRoute(
        "browser_screenshot", "hirarabrowser", "/browser_screenshot"
    ),
    "http_request": ToolRoute("http_request", "hirarahttp", "/http_request"),
    "http_history": ToolRoute("http_history", "hirarahttp", "/http_history"),
    "inspect_headers": ToolRoute(
        "inspect_headers", "hirarahttp", "/inspect_headers"
    ),
    "inspect_cookies": ToolRoute(
        "inspect_cookies", "hirarahttp", "/inspect_cookies"
    ),
    "inspect_response": ToolRoute(
        "inspect_response", "hirarahttp", "/inspect_response"
    ),
    "directory_enum": ToolRoute("directory_enum", "hirarahttp", "/directory_enum"),
    "file_read": ToolRoute("file_read", "hirarafs", "/file_read"),
    "file_write": ToolRoute("file_write", "hirarafs", "/file_write"),
}


def services() -> list[str]:
    """Unique backend service names, in a stable order."""
    seen: list[str] = []
    for route in TOOLS.values():
        if route.service not in seen:
            seen.append(route.service)
    return seen


__all__ = ["DEFAULT_PORTS", "TOOLS", "ToolRoute", "services"]
