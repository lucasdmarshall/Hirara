# Hirara tool roadmap

Target tool surface for the Hirara agent toolkit. Status tracks shipping
progress in this repo (hub + SDK + packages).

| # | Tool | Status | Package / notes |
|---|---|---|---|
| 1 | `web_search` | ✅ shipped | `hirara-web` / hub |
| 2 | `web_fetch` | ✅ shipped | `hirara-web` / hub |
| 3 | `dns_lookup` | ✅ shipped | `hiraranet` |
| 4 | `port_scan` | ✅ shipped | `hiraranet` |
| 5 | `service_enum` | ✅ shipped | `hiraranet` |
| 6 | `browser_open` | ✅ shipped | `hirarabrowser` |
| 7 | `browser_click` | ✅ shipped | `hirarabrowser` |
| 8 | `browser_type` | ✅ shipped | `hirarabrowser` |
| 9 | `browser_screenshot` | ✅ shipped | `hirarabrowser` |
| 10 | `http_request` | ✅ shipped | `hirarahttp` |
| 11 | `http_history` | ✅ shipped | `hirarahttp` |
| 12 | `inspect_headers` | ✅ shipped | `hirarahttp` |
| 13 | `inspect_cookies` | ✅ shipped | `hirarahttp` |
| 14 | `inspect_response` | ✅ shipped | `hirarahttp` |
| 15 | `directory_enum` | ✅ shipped | `hirarahttp` |
| 16 | `python_exec` | ✅ shipped (as `execute_code`) | `hiraracode` — alias / rename TBD |
| 17 | `file_read` | ✅ shipped | `hirarafs` |
| 18 | `file_write` | 📋 planned | `hirarafs` |
| 19 | `decode` | 📋 planned | `hirarautil` |
| 20 | `hash` | 📋 planned | `hirarautil` |
| 21 | `database_query` | 📋 planned | `hiraradb` |
| 22 | `database_schema` | 📋 planned | `hiraradb` |
| 23 | `application_logs` | 📋 planned | `hiraraops` |
| 24 | `process_list` | 📋 planned | `hiraraops` |
| 25 | `environment_read` | 📋 planned | `hiraraops` |
| 26 | `jwt_inspect` | 📋 planned | `hirarautil` |
| 27 | `jwt_decode` | 📋 planned | `hirarautil` |
| 28 | `request_replay` | 📋 planned | `hirarahttp` |
| 29 | `parameter_test` | 📋 planned | `hirarahttp` |
| 30 | `response_compare` | 📋 planned | `hirarahttp` |

## Package clusters

| Package | Tools |
|---|---|
| **`hiraranet`** | `dns_lookup`, `port_scan`, `service_enum` |
| **`hirarabrowser`** | `browser_open`, `browser_click`, `browser_type`, `browser_screenshot` |
| **`hirarahttp`** | `http_request`, `http_history`, `inspect_*`, `directory_enum`, `request_replay`, `parameter_test`, `response_compare` |
| **`hirarautil`** | `decode`, `hash`, `jwt_inspect`, `jwt_decode` |
| **`hirarafs`** | `file_read`, `file_write` |
| **`hiraradb`** | `database_query`, `database_schema` |
| **`hiraraops`** | `application_logs`, `process_list`, `environment_read` |
| Existing | `web_*`, `execute_code` / `python_exec`, PDF, OCR, Office, STT |

## Current focus

**`dns_lookup`**, **`port_scan`**, **`service_enum`** (`hiraranet/`),
**`browser_*`** (`hirarabrowser/`), the `hirarahttp` cluster, and **`file_read`**
(`hirarafs/`) are shipped.
Next up: `file_write` (`hirarafs`).

## Engineering conventions (all tools)

Same patterns as the rest of Hirara:

- Self-hosted, no third-party API keys.
- URL fetches go through [`hirara-core`](hirara-core/) (resolve-then-pin, redirect re-validation).
- Errors return in the JSON envelope (`"error": …`), not as HTTP 5xx.
- Hub registration: `hirara-hub` `DEFAULT_PORTS` + `TOOLS`, plus compose `HUB_*_URL`.
- Local SDK: `hirara.backends` entry point with `TOOL_NAMES` / `call_tool` / `tool_schemas`.
