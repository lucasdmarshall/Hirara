"""In-process tool execution for the hirara SDK.

Most Hirara tools are plain libraries — ``web_fetch``, ``pdf_read``,
``office_read`` and friends do their work in pure Python. When the matching
tool package is installed (``pip install hirara[local]``), the SDK can call it
directly, with no hub and no HTTP hop::

    import hirara
    hirara.pdf_read(path="report.pdf")   # runs in this process, no docker

Discovery is by entry point, not hard-coding. Each tool package advertises an
in-process backend under the ``hirara.backends`` group, pointing at a module
that exposes three names:

    TOOL_NAMES: tuple[str, ...]                 # which tools it serves
    async def call_tool(name, arguments) -> dict
    def tool_schemas() -> list[dict]

So a freshly written tool package joins local mode just by declaring the entry
point — the SDK needs no change. A tool whose package is not installed falls
through to the hub. ``execute_code`` has a local backend but still needs a
Docker daemon reachable from this process, and ``web_search`` needs your
SearXNG either way.
"""

from __future__ import annotations

import asyncio
import re
from importlib.metadata import entry_points

_GROUP = "hirara.backends"


class LocalBackends:
    """The set of in-process tool backends installed in this environment.

    Discovery is lazy and done once: importing every backend eagerly would drag
    in heavy dependencies the caller may never use.
    """

    def __init__(self) -> None:
        self._routes: dict[str, object] = {}  # tool name -> backend module
        self._modules: list[object] = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for ep in _iter_entry_points(_GROUP):
            try:
                module = ep.load()
                names = getattr(module, "TOOL_NAMES", ())
                if not names or not hasattr(module, "call_tool"):
                    continue
                for name in names:
                    self._routes.setdefault(name, module)
                self._modules.append(module)
            except Exception:
                # A broken or half-installed backend must not take down
                # discovery of the healthy ones.
                continue

    def has(self, name: str) -> bool:
        self._load()
        return name in self._routes

    def names(self) -> list[str]:
        self._load()
        return sorted(self._routes)

    def call(self, name: str, arguments: dict | None) -> dict:
        self._load()
        module = self._routes[name]
        try:
            return _run(module.call_tool(name, arguments or {}))
        except TypeError as exc:
            # A missing or unknown argument is bad input, so it gets the same
            # {"error": ...} envelope as any other bad input. The HTTP service
            # and MCP servers validate against the schema first; this path
            # hands the dict straight to the tool method.
            if not _raised_by_call_site(exc, module.call_tool):
                raise
            return {"error": f"{name}: {_ARG_PREFIX.sub('', str(exc))}"}

    def schemas(self) -> list[dict]:
        self._load()
        out: list[dict] = []
        for module in self._modules:
            getter = getattr(module, "tool_schemas", None)
            if getter is None:
                continue
            try:
                out.extend(getter())
            except Exception:
                continue
        return out


# "Toolset.decode() missing 1 required ..." -> "missing 1 required ..."
_ARG_PREFIX = re.compile(r"^[\w.]+\(\) ")


def _raised_by_call_site(exc: BaseException, call_tool) -> bool:
    """Whether ``exc`` was raised while binding arguments inside ``call_tool``.

    A bad ``**arguments`` fails before the tool method has a frame of its own,
    so the traceback ends in ``call_tool`` itself. A TypeError raised deeper,
    inside the tool's own code, is a real bug and must not be relabelled as
    bad input.
    """
    code = getattr(call_tool, "__code__", None)
    tb = exc.__traceback__
    if code is None or tb is None:
        return False
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame.f_code is code


def _iter_entry_points(group: str):
    """entry_points(group=...) is the modern API; older stdlib returns a dict."""
    try:
        return list(entry_points(group=group))
    except TypeError:  # Python < 3.10 fallback (we require 3.11, but be safe)
        return list(entry_points().get(group, []))


def _run(coro):
    """Drive an async ``call_tool`` from the SDK's synchronous surface.

    The common case — no event loop running — is a plain ``asyncio.run``. If the
    caller is already inside a loop (e.g. a notebook or an async app), we run the
    coroutine on a private loop in a worker thread so we never touch theirs.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()
