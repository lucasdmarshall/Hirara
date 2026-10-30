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
    "hirarautil": 9000,
    "hiraradb": 9100,
    "hiraraops": 9200,
    "hiraraaudio": 9300,
    "hiraradata": 9400,
    "hiraramedia": 9500,
    "hiraraagent": 9600,
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
    "document_index": ToolRoute("document_index", "hirarafs", "/document_index"),
    "document_search": ToolRoute("document_search", "hirarafs", "/document_search"),
    "document_remove": ToolRoute("document_remove", "hirarafs", "/document_remove"),
    "symbolic_math": ToolRoute("symbolic_math", "hirarautil", "/symbolic_math"),
    "stackexchange_search": ToolRoute("stackexchange_search", "websearch", "/stackexchange_search"),
    "books_search": ToolRoute("books_search", "websearch", "/books_search"),
    "weather": ToolRoute("weather", "websearch", "/weather"),

    "file_copy": ToolRoute("file_copy", "hirarafs", "/file_copy"),
    "file_move": ToolRoute("file_move", "hirarafs", "/file_move"),
    "file_rename": ToolRoute("file_rename", "hirarafs", "/file_rename"),
    "file_delete": ToolRoute("file_delete", "hirarafs", "/file_delete"),
    "json_query": ToolRoute("json_query", "hirarautil", "/json_query"),
    "arxiv_search": ToolRoute("arxiv_search", "websearch", "/arxiv_search"),
    "pubmed_search": ToolRoute("pubmed_search", "websearch", "/pubmed_search"),

    "web_search": ToolRoute("web_search", "websearch", "/web_search"),
    "web_fetch": ToolRoute("web_fetch", "websearch", "/web_fetch"),
    "transcribe": ToolRoute("transcribe", "hirarastt", "/transcribe", experimental=True),
    "pdf_read": ToolRoute("pdf_read", "hirarapdf", "/pdf_read"),
    "pdf_info": ToolRoute("pdf_info", "hirarapdf", "/pdf_info"),
    "pdf_create": ToolRoute("pdf_create", "hirarapdf", "/pdf_create"),
    "html_to_pdf": ToolRoute("html_to_pdf", "hirarapdf", "/html_to_pdf"),
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
    "request_replay": ToolRoute("request_replay", "hirarahttp", "/request_replay"),
    "parameter_test": ToolRoute("parameter_test", "hirarahttp", "/parameter_test"),
    "response_compare": ToolRoute(
        "response_compare", "hirarahttp", "/response_compare"
    ),
    "file_read": ToolRoute("file_read", "hirarafs", "/file_read"),
    "file_write": ToolRoute("file_write", "hirarafs", "/file_write"),
    "decode": ToolRoute("decode", "hirarautil", "/decode"),
    "hash": ToolRoute("hash", "hirarautil", "/hash"),
    "jwt_inspect": ToolRoute("jwt_inspect", "hirarautil", "/jwt_inspect"),
    "jwt_decode": ToolRoute("jwt_decode", "hirarautil", "/jwt_decode"),
    "database_query": ToolRoute("database_query", "hiraradb", "/database_query"),
    "database_schema": ToolRoute(
        "database_schema", "hiraradb", "/database_schema"
    ),
    "application_logs": ToolRoute(
        "application_logs", "hiraraops", "/application_logs"
    ),
    "process_list": ToolRoute("process_list", "hiraraops", "/process_list"),
    "environment_read": ToolRoute(
        "environment_read", "hiraraops", "/environment_read"
    ),
    "audio_info": ToolRoute("audio_info", "hiraraaudio", "/audio_info"),
    "audio_profile": ToolRoute("audio_profile", "hiraraaudio", "/audio_profile"),
    "audio_check": ToolRoute("audio_check", "hiraraaudio", "/audio_check"),
    "audio_fix": ToolRoute("audio_fix", "hiraraaudio", "/audio_fix"),
    "audio_compare": ToolRoute("audio_compare", "hiraraaudio", "/audio_compare"),
    "audio_find": ToolRoute("audio_find", "hiraraaudio", "/audio_find"),
    "audio_fingerprint": ToolRoute(
        "audio_fingerprint", "hiraraaudio", "/audio_fingerprint"
    ),
    "audio_split": ToolRoute("audio_split", "hiraraaudio", "/audio_split"),
    "audio_tighten": ToolRoute("audio_tighten", "hiraraaudio", "/audio_tighten"),
    "audio_spectrogram": ToolRoute(
        "audio_spectrogram", "hiraraaudio", "/audio_spectrogram"
    ),
    "audio_tones": ToolRoute("audio_tones", "hiraraaudio", "/audio_tones"),
    "audio_speak": ToolRoute("audio_speak", "hiraraaudio", "/audio_speak"),
    "audio_sonify": ToolRoute("audio_sonify", "hiraraaudio", "/audio_sonify"),
    "audio_watch": ToolRoute("audio_watch", "hiraraaudio", "/audio_watch"),
    "file_edit": ToolRoute("file_edit", "hirarafs", "/file_edit"),
    "file_search": ToolRoute("file_search", "hirarafs", "/file_search"),
    "file_list": ToolRoute("file_list", "hirarafs", "/file_list"),
    "archive_list": ToolRoute("archive_list", "hirarafs", "/archive_list"),
    "archive_extract": ToolRoute("archive_extract", "hirarafs", "/archive_extract"),
    "time_now": ToolRoute("time_now", "hirarautil", "/time_now"),
    "date_calc": ToolRoute("date_calc", "hirarautil", "/date_calc"),
    "schema_validate": ToolRoute("schema_validate", "hirarautil", "/schema_validate"),
    "link_check": ToolRoute("link_check", "hirarahttp", "/link_check"),
    "site_map": ToolRoute("site_map", "hirarahttp", "/site_map"),
    "web_watch": ToolRoute("web_watch", "hirarahttp", "/web_watch"),
    "secret_list": ToolRoute("secret_list", "hirarahttp", "/secret_list"),
    "job_start": ToolRoute("job_start", "hiraracode", "/job_start"),
    "job_status": ToolRoute("job_status", "hiraracode", "/job_status"),
    "job_stop": ToolRoute("job_stop", "hiraracode", "/job_stop"),
    "email_read": ToolRoute("email_read", "hirarareader", "/email_read"),
    "data_profile": ToolRoute("data_profile", "hiraradata", "/data_profile"),
    "chart_render": ToolRoute("chart_render", "hiraradata", "/chart_render"),
    "diagram_render": ToolRoute("diagram_render", "hiraradata", "/diagram_render"),
    "video_profile": ToolRoute("video_profile", "hiraramedia", "/video_profile"),
    "image_compare": ToolRoute("image_compare", "hiraramedia", "/image_compare"),
    "barcode_read": ToolRoute("barcode_read", "hiraramedia", "/barcode_read"),
    "qr_generate": ToolRoute("qr_generate", "hiraramedia", "/qr_generate"),
    "memory": ToolRoute("memory", "hiraraagent", "/memory"),
    "ask_human": ToolRoute("ask_human", "hiraraagent", "/ask_human"),
    "schedule": ToolRoute("schedule", "hiraraagent", "/schedule"),
    "wait_until": ToolRoute("wait_until", "hiraraagent", "/wait_until"),
}


def services() -> list[str]:
    """Unique backend service names, in a stable order."""
    seen: list[str] = []
    for route in TOOLS.values():
        if route.service not in seen:
            seen.append(route.service)
    return seen


__all__ = ["DEFAULT_PORTS", "TOOLS", "ToolRoute", "services"]
