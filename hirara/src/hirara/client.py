"""The Hirara Python client — call the hub's tools like functions.

    import hirara
    hirara.configure("http://localhost:8080", token="...")   # or env HIRARA_HUB_URL
    print(hirara.web_search("rust borrow checker", max_results=5))
    print(hirara.office_read(path="deck.pptx")["markdown"])

Or with an explicit client::

    from hirara import Client
    hub = Client("http://localhost:8080")
    hub.pdf_read(path="report.pdf")

The client is thin: it talks to a running hub over HTTP. When you pass a local
``path=``, the client reads the file and sends it as base64 — so it works even
when the hub has no access to your filesystem (the default for a networked hub).
"""

from __future__ import annotations

import base64 as _b64
import os

import httpx

from ._local import LocalBackends

DEFAULT_URL = "http://localhost:8080"

# Discovered once per process: the in-process tool backends installed here
# (see hirara._local). Shared by every Client — it reflects the environment,
# not any one connection.
_BACKENDS = LocalBackends()


class HiraraError(RuntimeError):
    """Transport-level failure: the hub is unreachable or returned junk."""


class HiraraToolError(RuntimeError):
    """A tool ran but reported an error (e.g. blocked URL, bad input)."""

    def __init__(self, tool: str, error: str, response: dict) -> None:
        super().__init__(f"{tool}: {error}")
        self.tool = tool
        self.error = error
        self.response = response


def _encode_file(path: str) -> str:
    with open(os.path.expanduser(path), "rb") as fh:
        return _b64.b64encode(fh.read()).decode("ascii")


class Client:
    """A connection to a Hirara hub."""

    def __init__(
        self,
        url: str | None = None,
        *,
        token: str | None = None,
        timeout: float = 120.0,
        local: bool | str = "auto",
    ) -> None:
        self.url = (url or os.getenv("HIRARA_HUB_URL") or DEFAULT_URL).rstrip("/")
        # Did the caller actually name a hub, or are we on the default? In "auto"
        # mode an explicit hub wins (if you told us your hub, we use it); with no
        # hub configured we run tools in-process instead.
        self._hub_explicit = url is not None or os.getenv("HIRARA_HUB_URL") is not None
        self.token = token if token is not None else os.getenv("HIRARA_HUB_TOKEN")
        self.timeout = timeout
        # local=True  → run tools in-process only (error if no local backend);
        # local=False → always go to the hub over HTTP (the original behaviour);
        # local="auto" (default) → run in-process when a backend is installed for
        #   the tool, otherwise fall through to the hub. A plain `pip install
        #   hirara` installs no backends, so "auto" behaves exactly like the old
        #   HTTP client until you `pip install hirara[local]`.
        self.local = local
        self._client: httpx.Client | None = None

    # allow dependency injection in tests
    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.Client(base_url=self.url, headers=headers, timeout=self.timeout)

    # --- low level ---

    def _use_local(self, name: str) -> bool:
        """Whether ``name`` should run in-process for this client."""
        if self.local is True:
            return _BACKENDS.has(name)
        if self.local is False:
            return False
        # "auto": an explicitly configured hub takes precedence; with no hub
        # configured, run in-process when a backend is installed for this tool.
        if self._hub_explicit:
            return False
        return _BACKENDS.has(name)

    def call(self, name: str, arguments: dict | None = None, *, raise_on_error: bool = True) -> dict:
        """Invoke a tool by name with a raw arguments dict.

        Runs in-process when a local backend is installed for the tool (unless
        ``local=False``); otherwise forwards to the hub over HTTP.
        """
        if self._use_local(name):
            data = _BACKENDS.call(name, arguments)
            if raise_on_error and isinstance(data, dict) and data.get("error"):
                raise HiraraToolError(name, data["error"], data)
            return data
        if self.local is True:
            raise HiraraError(
                f"{name!r} has no in-process backend installed and local mode is "
                f"forced (local=True). Install one (e.g. pip install "
                f"hirara[local]) or point at a hub (hirara.configure('http://…'))."
            )
        return self._call_http(name, arguments, raise_on_error=raise_on_error)

    def _call_http(self, name: str, arguments: dict | None = None, *, raise_on_error: bool = True) -> dict:
        client = self._http()
        try:
            resp = client.post("/call", json={"name": name, "arguments": arguments or {}})
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise HiraraError("unauthorized — set the hub token (HIRARA_HUB_TOKEN)") from exc
            raise HiraraError(f"hub returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise HiraraError(f"could not reach hub at {self.url}: {exc}") from exc
        except ValueError as exc:
            raise HiraraError("hub returned a non-JSON response") from exc
        finally:
            if self._client is None:
                client.close()

        if raise_on_error and isinstance(data, dict) and data.get("error"):
            raise HiraraToolError(name, data["error"], data)
        return data

    def tools(self) -> list[dict]:
        """The aggregated tool schemas: in-process backends plus the hub.

        Local schemas come first and win on name collisions (that is the backend
        that would actually run). When local mode can answer, a hub that is down
        is not fatal — the local tools are still listed.
        """
        # Mirror _use_local so tools() lists what would actually run.
        local_active = self.local is True or (self.local == "auto" and not self._hub_explicit)
        hub_active = self.local is not True

        local = _BACKENDS.schemas() if local_active else []
        remote: list[dict] = []
        if hub_active:
            try:
                remote = self._get("/schemas").get("tools", [])
            except HiraraError:
                # If local can answer, an unreachable hub is not fatal; otherwise
                # preserve the original behaviour and surface the error.
                if not local_active:
                    raise
                remote = []

        seen: set = set()
        merged: list[dict] = []
        for schema in [*local, *remote]:
            name = schema.get("name")
            if name in seen:
                continue
            seen.add(name)
            merged.append(schema)
        return merged

    def health(self) -> dict:
        return self._get("/health")

    def _get(self, path: str) -> dict:
        client = self._http()
        try:
            resp = client.get(path)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise HiraraError(f"could not reach hub at {self.url}: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    # --- file helper ---

    def _source(self, prefix: str, path, url, base64) -> dict:
        given = [x for x in (path, url, base64) if x]
        if len(given) != 1:
            raise ValueError("provide exactly one of path=, url=, or base64=")
        if path:
            return {f"{prefix}_base64": _encode_file(path)}
        if url:
            return {f"{prefix}_url": url}
        return {f"{prefix}_base64": base64}

    # --- typed tools ---

    def web_search(self, query: str, *, max_results: int | None = None, **extra) -> dict:
        args = {"query": query, **extra}
        if max_results is not None:
            args["max_results"] = max_results
        return self.call("web_search", args)

    def web_fetch(self, url: str, *, max_chars: int | None = None, **extra) -> dict:
        args = {"url": url, **extra}
        if max_chars is not None:
            args["max_chars"] = max_chars
        return self.call("web_fetch", args)

    def pdf_read(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("pdf_read", {**self._source("pdf", path, url, base64), **extra})

    def pdf_info(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("pdf_info", {**self._source("pdf", path, url, base64), **extra})

    def pdf_create(self, content: str, *, format: str = "markdown", **extra) -> dict:
        return self.call("pdf_create", {"content": content, "format": format, **extra})

    def execute_code(self, language: str, code: str, **extra) -> dict:
        return self.call("execute_code", {"language": language, "code": code, **extra})

    def ocr_read(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("ocr_read", {**self._source("file", path, url, base64), **extra})

    def form_extract(self, *, path=None, url=None, base64=None, **extra) -> dict:
        return self.call("form_extract", {**self._source("file", path, url, base64), **extra})

    def office_read(self, *, path=None, url=None, base64=None, **extra) -> dict:
        args = {**self._source("file", path, url, base64), **extra}
        if path and "filename" not in args:
            args["filename"] = os.path.basename(path)
        return self.call("office_read", args)

    def dns_lookup(
        self,
        name: str,
        *,
        record_types: list[str] | None = None,
        nameserver: str | None = None,
        **extra,
    ) -> dict:
        args = {"name": name, **extra}
        if record_types is not None:
            args["record_types"] = record_types
        if nameserver is not None:
            args["nameserver"] = nameserver
        return self.call("dns_lookup", args)

    def port_scan(
        self,
        host: str,
        *,
        ports: list[int | str] | str | None = None,
        timeout: float | None = None,
        concurrency: int | None = None,
        **extra,
    ) -> dict:
        args = {"host": host, **extra}
        if ports is not None:
            args["ports"] = ports
        if timeout is not None:
            args["timeout"] = timeout
        if concurrency is not None:
            args["concurrency"] = concurrency
        return self.call("port_scan", args)

    def service_enum(
        self,
        host: str,
        *,
        ports: list[int | str] | str | None = None,
        timeout: float | None = None,
        concurrency: int | None = None,
        tls: bool | None = None,
        **extra,
    ) -> dict:
        args = {"host": host, **extra}
        if ports is not None:
            args["ports"] = ports
        if timeout is not None:
            args["timeout"] = timeout
        if concurrency is not None:
            args["concurrency"] = concurrency
        if tls is not None:
            args["tls"] = tls
        return self.call("service_enum", args)

    def browser_open(
        self,
        url: str,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
        include_text: bool = False,
        **extra,
    ) -> dict:
        args = {"url": url, "include_text": include_text, **extra}
        if session_id is not None:
            args["session_id"] = session_id
        if timeout is not None:
            args["timeout"] = timeout
        return self.call("browser_open", args)

    def browser_click(
        self,
        session_id: str,
        selector: str,
        *,
        timeout: float | None = None,
        button: str = "left",
        click_count: int = 1,
        **extra,
    ) -> dict:
        args = {
            "session_id": session_id,
            "selector": selector,
            "button": button,
            "click_count": click_count,
            **extra,
        }
        if timeout is not None:
            args["timeout"] = timeout
        return self.call("browser_click", args)

    def browser_type(
        self,
        session_id: str,
        selector: str,
        text: str,
        *,
        timeout: float | None = None,
        clear: bool = True,
        press_enter: bool = False,
        delay_ms: float | None = None,
        **extra,
    ) -> dict:
        args = {
            "session_id": session_id,
            "selector": selector,
            "text": text,
            "clear": clear,
            "press_enter": press_enter,
            **extra,
        }
        if timeout is not None:
            args["timeout"] = timeout
        if delay_ms is not None:
            args["delay_ms"] = delay_ms
        return self.call("browser_type", args)

    def browser_screenshot(
        self,
        session_id: str,
        *,
        full_page: bool = False,
        selector: str | None = None,
        image_format: str = "png",
        quality: int | None = None,
        timeout: float | None = None,
        **extra,
    ) -> dict:
        args = {
            "session_id": session_id,
            "full_page": full_page,
            "image_format": image_format,
            **extra,
        }
        if selector is not None:
            args["selector"] = selector
        if quality is not None:
            args["quality"] = quality
        if timeout is not None:
            args["timeout"] = timeout
        return self.call("browser_screenshot", args)

    def http_request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        max_redirects: int | None = None,
        max_bytes: int | None = None,
        **extra,
    ) -> dict:
        args = {
            "url": url,
            "method": method,
            "follow_redirects": follow_redirects,
            **extra,
        }
        if headers is not None:
            args["headers"] = headers
        if body is not None:
            args["body"] = body
        if timeout is not None:
            args["timeout"] = timeout
        if max_redirects is not None:
            args["max_redirects"] = max_redirects
        if max_bytes is not None:
            args["max_bytes"] = max_bytes
        return self.call("http_request", args)

    def http_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        id: str | None = None,
        include_body: bool = False,
        clear: bool = False,
        **extra,
    ) -> dict:
        args = {
            "limit": limit,
            "offset": offset,
            "include_body": include_body,
            "clear": clear,
            **extra,
        }
        if id is not None:
            args["id"] = id
        return self.call("http_history", args)

    def inspect_headers(
        self,
        *,
        id: str | None = None,
        which: str = "response",
        headers: dict[str, str] | None = None,
        **extra,
    ) -> dict:
        args = {"which": which, **extra}
        if id is not None:
            args["id"] = id
        if headers is not None:
            args["headers"] = headers
        return self.call("inspect_headers", args)

    def inspect_cookies(
        self,
        *,
        id: str | None = None,
        which: str = "response",
        headers: dict[str, str] | None = None,
        **extra,
    ) -> dict:
        args = {"which": which, **extra}
        if id is not None:
            args["id"] = id
        if headers is not None:
            args["headers"] = headers
        return self.call("inspect_cookies", args)

    def inspect_response(
        self,
        *,
        id: str | None = None,
        include_body: bool = False,
        preview_chars: int = 512,
        status: int | None = None,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        body_encoding: str | None = None,
        **extra,
    ) -> dict:
        args = {"include_body": include_body, "preview_chars": preview_chars, **extra}
        if id is not None:
            args["id"] = id
        if status is not None:
            args["status"] = status
        if body is not None:
            args["body"] = body
        if headers is not None:
            args["headers"] = headers
        if body_encoding is not None:
            args["body_encoding"] = body_encoding
        return self.call("inspect_response", args)

    def directory_enum(
        self,
        url: str,
        *,
        paths: list[str] | str | None = None,
        method: str = "HEAD",
        timeout: float | None = None,
        concurrency: int | None = None,
        include_not_found: bool = False,
        **extra,
    ) -> dict:
        args = {
            "url": url,
            "method": method,
            "include_not_found": include_not_found,
            **extra,
        }
        if paths is not None:
            args["paths"] = paths
        if timeout is not None:
            args["timeout"] = timeout
        if concurrency is not None:
            args["concurrency"] = concurrency
        return self.call("directory_enum", args)

    def request_replay(
        self,
        id: str,
        *,
        url: str | None = None,
        method: str | None = None,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        merge_headers: bool = True,
        timeout: float | None = None,
        follow_redirects: bool = True,
        max_redirects: int | None = None,
        max_bytes: int | None = None,
        **extra,
    ) -> dict:
        args = {
            "id": id,
            "merge_headers": merge_headers,
            "follow_redirects": follow_redirects,
            **extra,
        }
        if url is not None:
            args["url"] = url
        if method is not None:
            args["method"] = method
        if headers is not None:
            args["headers"] = headers
        if body is not None:
            args["body"] = body
        if timeout is not None:
            args["timeout"] = timeout
        if max_redirects is not None:
            args["max_redirects"] = max_redirects
        if max_bytes is not None:
            args["max_bytes"] = max_bytes
        return self.call("request_replay", args)

    def parameter_test(
        self,
        location: str,
        name: str,
        values: list[str] | str,
        *,
        id: str | None = None,
        url: str | None = None,
        method: str | None = None,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        max_redirects: int | None = None,
        max_bytes: int | None = None,
        concurrency: int | None = None,
        include_body: bool = False,
        body_preview_chars: int = 200,
        **extra,
    ) -> dict:
        args = {
            "location": location,
            "name": name,
            "values": values,
            "follow_redirects": follow_redirects,
            "include_body": include_body,
            "body_preview_chars": body_preview_chars,
            **extra,
        }
        if id is not None:
            args["id"] = id
        if url is not None:
            args["url"] = url
        if method is not None:
            args["method"] = method
        if headers is not None:
            args["headers"] = headers
        if body is not None:
            args["body"] = body
        if timeout is not None:
            args["timeout"] = timeout
        if max_redirects is not None:
            args["max_redirects"] = max_redirects
        if max_bytes is not None:
            args["max_bytes"] = max_bytes
        if concurrency is not None:
            args["concurrency"] = concurrency
        return self.call("parameter_test", args)

    def response_compare(
        self,
        *,
        left_id: str | None = None,
        right_id: str | None = None,
        left_status: int | None = None,
        right_status: int | None = None,
        left_headers: dict[str, str] | None = None,
        right_headers: dict[str, str] | None = None,
        left_body: str | None = None,
        right_body: str | None = None,
        compare_headers: bool = True,
        compare_body: bool = True,
        ignore_headers: list[str] | str | None = None,
        **extra,
    ) -> dict:
        args = {
            "compare_headers": compare_headers,
            "compare_body": compare_body,
            **extra,
        }
        if left_id is not None:
            args["left_id"] = left_id
        if right_id is not None:
            args["right_id"] = right_id
        if left_status is not None:
            args["left_status"] = left_status
        if right_status is not None:
            args["right_status"] = right_status
        if left_headers is not None:
            args["left_headers"] = left_headers
        if right_headers is not None:
            args["right_headers"] = right_headers
        if left_body is not None:
            args["left_body"] = left_body
        if right_body is not None:
            args["right_body"] = right_body
        if ignore_headers is not None:
            args["ignore_headers"] = ignore_headers
        return self.call("response_compare", args)

    def file_read(
        self,
        path: str,
        *,
        encoding: str | None = None,
        max_bytes: int | None = None,
        offset: int = 0,
        **extra,
    ) -> dict:
        args = {"path": path, "offset": offset, **extra}
        if encoding is not None:
            args["encoding"] = encoding
        if max_bytes is not None:
            args["max_bytes"] = max_bytes
        return self.call("file_read", args)

    def file_write(
        self,
        path: str,
        content: str,
        *,
        encoding: str | None = None,
        append: bool = False,
        create_parents: bool = False,
        overwrite: bool = True,
        max_bytes: int | None = None,
        **extra,
    ) -> dict:
        args = {
            "path": path,
            "content": content,
            "append": append,
            "create_parents": create_parents,
            "overwrite": overwrite,
            **extra,
        }
        if encoding is not None:
            args["encoding"] = encoding
        if max_bytes is not None:
            args["max_bytes"] = max_bytes
        return self.call("file_write", args)

    def decode(
        self,
        input: str,
        *,
        format: str = "auto",
        **extra,
    ) -> dict:
        return self.call("decode", {"input": input, "format": format, **extra})

    def hash(
        self,
        input: str,
        *,
        algorithms: list[str] | str | None = None,
        encoding: str | None = None,
        output_format: str | None = None,
        **extra,
    ) -> dict:
        args = {"input": input, **extra}
        if algorithms is not None:
            args["algorithms"] = algorithms
        if encoding is not None:
            args["encoding"] = encoding
        if output_format is not None:
            args["output_format"] = output_format
        return self.call("hash", args)

    def jwt_inspect(
        self,
        input: str,
        *,
        include_claims: bool = False,
        **extra,
    ) -> dict:
        return self.call(
            "jwt_inspect",
            {"input": input, "include_claims": include_claims, **extra},
        )

    def jwt_decode(
        self,
        input: str,
        *,
        verify: bool = False,
        secret: str | None = None,
        include_signature: bool = False,
        **extra,
    ) -> dict:
        args = {
            "input": input,
            "verify": verify,
            "include_signature": include_signature,
            **extra,
        }
        if secret is not None:
            args["secret"] = secret
        return self.call("jwt_decode", args)

    def database_query(
        self,
        sql: str,
        *,
        params: list | dict | None = None,
        database: str | None = None,
        path: str | None = None,
        max_rows: int | None = None,
        readonly: bool | None = None,
        **extra,
    ) -> dict:
        args = {"sql": sql, **extra}
        if params is not None:
            args["params"] = params
        if database is not None:
            args["database"] = database
        if path is not None:
            args["path"] = path
        if max_rows is not None:
            args["max_rows"] = max_rows
        if readonly is not None:
            args["readonly"] = readonly
        return self.call("database_query", args)

    def database_schema(
        self,
        *,
        database: str | None = None,
        path: str | None = None,
        table: str | None = None,
        include_views: bool = True,
        include_indexes: bool = False,
        include_foreign_keys: bool = False,
        include_sql: bool = False,
        max_tables: int | None = None,
        **extra,
    ) -> dict:
        args = {
            "include_views": include_views,
            "include_indexes": include_indexes,
            "include_foreign_keys": include_foreign_keys,
            "include_sql": include_sql,
            **extra,
        }
        if database is not None:
            args["database"] = database
        if path is not None:
            args["path"] = path
        if table is not None:
            args["table"] = table
        if max_tables is not None:
            args["max_tables"] = max_tables
        return self.call("database_schema", args)

    def application_logs(
        self,
        *,
        path: str | None = None,
        source: str | None = None,
        lines: int | None = None,
        from_end: bool = True,
        pattern: str | None = None,
        level: str | None = None,
        max_bytes: int | None = None,
        **extra,
    ) -> dict:
        args = {"from_end": from_end, **extra}
        if path is not None:
            args["path"] = path
        if source is not None:
            args["source"] = source
        if lines is not None:
            args["lines"] = lines
        if pattern is not None:
            args["pattern"] = pattern
        if level is not None:
            args["level"] = level
        if max_bytes is not None:
            args["max_bytes"] = max_bytes
        return self.call("application_logs", args)

    def process_list(
        self,
        *,
        pattern: str | None = None,
        user: str | None = None,
        pid: int | None = None,
        max_processes: int | None = None,
        include_cmdline: bool = True,
        **extra,
    ) -> dict:
        args = {"include_cmdline": include_cmdline, **extra}
        if pattern is not None:
            args["pattern"] = pattern
        if user is not None:
            args["user"] = user
        if pid is not None:
            args["pid"] = pid
        if max_processes is not None:
            args["max_processes"] = max_processes
        return self.call("process_list", args)

    def environment_read(
        self,
        *,
        pid: int | None = None,
        keys: list[str] | str | None = None,
        pattern: str | None = None,
        include_values: bool = True,
        redact: bool | None = None,
        max_vars: int | None = None,
        **extra,
    ) -> dict:
        args = {"include_values": include_values, **extra}
        if pid is not None:
            args["pid"] = pid
        if keys is not None:
            args["keys"] = keys
        if pattern is not None:
            args["pattern"] = pattern
        if redact is not None:
            args["redact"] = redact
        if max_vars is not None:
            args["max_vars"] = max_vars
        return self.call("environment_read", args)


# --- module-level convenience: `import hirara; hirara.web_search(...)` ---

_default: Client | None = None


def configure(
    url: str | None = None,
    *,
    token: str | None = None,
    timeout: float = 120.0,
    local: bool | str = "auto",
) -> Client:
    """Configure how the module-level functions run tools.

    Pass a hub ``url`` to forward tools over HTTP. Leave it out and install
    ``hirara[local]`` to run tools in this process with no hub. ``local`` may be
    ``"auto"`` (default: in-process when available, else the hub), ``True``
    (in-process only), or ``False`` (always the hub).
    """
    global _default
    _default = Client(url, token=token, timeout=timeout, local=local)
    return _default


def _get_default() -> Client:
    global _default
    if _default is None:
        _default = Client()
    return _default


def _delegate(name):
    def method(*args, **kwargs):
        return getattr(_get_default(), name)(*args, **kwargs)

    method.__name__ = name
    return method


web_search = _delegate("web_search")
web_fetch = _delegate("web_fetch")
pdf_read = _delegate("pdf_read")
pdf_info = _delegate("pdf_info")
pdf_create = _delegate("pdf_create")
execute_code = _delegate("execute_code")
ocr_read = _delegate("ocr_read")
form_extract = _delegate("form_extract")
office_read = _delegate("office_read")
dns_lookup = _delegate("dns_lookup")
port_scan = _delegate("port_scan")
service_enum = _delegate("service_enum")
browser_open = _delegate("browser_open")
browser_click = _delegate("browser_click")
browser_type = _delegate("browser_type")
browser_screenshot = _delegate("browser_screenshot")
http_request = _delegate("http_request")
http_history = _delegate("http_history")
inspect_headers = _delegate("inspect_headers")
inspect_cookies = _delegate("inspect_cookies")
inspect_response = _delegate("inspect_response")
directory_enum = _delegate("directory_enum")
request_replay = _delegate("request_replay")
parameter_test = _delegate("parameter_test")
response_compare = _delegate("response_compare")
file_read = _delegate("file_read")
file_write = _delegate("file_write")
decode = _delegate("decode")
hash = _delegate("hash")
jwt_inspect = _delegate("jwt_inspect")
jwt_decode = _delegate("jwt_decode")
database_query = _delegate("database_query")
database_schema = _delegate("database_schema")
application_logs = _delegate("application_logs")
process_list = _delegate("process_list")
environment_read = _delegate("environment_read")
call = _delegate("call")
tools = _delegate("tools")
health = _delegate("health")


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
    "request_replay",
    "parameter_test",
    "response_compare",
    "file_read",
    "file_write",
    "decode",
    "hash",
    "jwt_inspect",
    "jwt_decode",
    "database_query",
    "database_schema",
    "application_logs",
    "process_list",
    "environment_read",
]
