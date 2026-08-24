"""Hirara — the Python SDK for the Hirara agent tools. No API keys.

Two ways to run a tool, same call surface:

    import hirara

    # In-process — no hub, no docker (pip install hirara[local]):
    hirara.pdf_read(path="report.pdf")
    hirara.web_fetch("https://example.com")

    # Or forward to a running hub (see the `hirara-hub` gateway):
    hirara.configure("http://localhost:8080")
    hirara.web_search("rust borrow checker", max_results=5)

By default (`local="auto"`) a tool runs in-process when its package is
installed, and otherwise falls through to the hub — so tools that need a service
(`execute_code`, `web_search` against your own SearXNG) keep working via the hub.
"""

from .client import (
    Client,
    HiraraError,
    HiraraToolError,
    call,
    configure,
    dns_lookup,
    execute_code,
    form_extract,
    health,
    ocr_read,
    office_read,
    pdf_create,
    pdf_info,
    pdf_read,
    port_scan,
    service_enum,
    browser_open,
    browser_click,
    browser_type,
    browser_screenshot,
    http_request,
    http_history,
    inspect_headers,
    inspect_cookies,
    inspect_response,
    directory_enum,
    file_read,
    tools,
    web_fetch,
    web_search,
)

__all__ = [
    "Client",
    "HiraraError",
    "HiraraToolError",
    "configure",
    "call",
    "tools",
    "health",
    "web_search",
    "web_fetch",
    "pdf_read",
    "pdf_info",
    "pdf_create",
    "execute_code",
    "ocr_read",
    "form_extract",
    "office_read",
    "dns_lookup",
    "port_scan",
    "service_enum",
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "http_request",
    "http_history",
    "inspect_headers",
    "inspect_cookies",
    "inspect_response",
    "directory_enum",
    "file_read",
]

__version__ = "0.2.0"

__banner__ = (
    "    __  __________  ___    ____  ___ \n"
    "   / / / /  _/ __ \\/   |  / __ \\/   |\n"
    "  / /_/ // // /_/ / /| | / /_/ / /| |\n"
    " / __  // // _, _/ ___ |/ _, _/ ___ |\n"
    "/_/ /_/___/_/ |_/_/  |_/_/ |_/_/  |_|"
)
