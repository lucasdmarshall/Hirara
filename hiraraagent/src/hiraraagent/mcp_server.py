"""MCP front end — memory, human-in-the-loop, reminders and waiting.

    python -m hiraraagent.mcp_server                       # stdio
    python -m hiraraagent.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import tools as T
from .tools import Toolset

server = MCPServer(
    name="hiraraagent",
    version="0.1.0",
    instructions=(
        "State for an agent across sessions. memory keeps notes (search before redoing "
        "work). ask_human asks a person a question or for approval and returns a "
        "request_id; never take an approval-gated action until the answer is approve. "
        "schedule sets reminders for later follow-ups; wait_until blocks until an "
        "answer, a due reminder or a time. No API keys."
    ),
)

_toolset = Toolset.from_env()


@server.tool(name="memory", description=T.MEMORY_SCHEMA["description"])
async def memory_tool(action: str, key: str | None = None, value: Any = None,
                      tags: list[str] | None = None, ttl_seconds: float | None = None,
                      query: str | None = None, limit: int = 20, offset: int = 0,
                      namespace: str | None = None) -> dict:
    return await _toolset.memory(action=action, key=key, value=value, tags=tags,
                                 ttl_seconds=ttl_seconds, query=query, limit=limit,
                                 offset=offset, namespace=namespace)


@server.tool(name="ask_human", description=T.ASK_HUMAN_SCHEMA["description"])
async def ask_human_tool(action: str, question: str | None = None, kind: str = "question",
                         options: list[str] | None = None, allow_free_text: bool = False,
                         context: str | None = None, urgency: str = "normal",
                         expires_in_seconds: float | None = None, request_id: str | None = None,
                         namespace: str | None = None) -> dict:
    return await _toolset.ask_human(action=action, question=question, kind=kind, options=options,
                                    allow_free_text=allow_free_text, context=context,
                                    urgency=urgency, expires_in_seconds=expires_in_seconds,
                                    request_id=request_id, namespace=namespace)


@server.tool(name="schedule", description=T.SCHEDULE_SCHEMA["description"])
async def schedule_tool(action: str, title: str | None = None, note: str | None = None,
                        at: str | None = None, in_seconds: float | None = None,
                        repeat_seconds: float | None = None, reminder_id: str | None = None,
                        include_done: bool = False, namespace: str | None = None) -> dict:
    return await _toolset.schedule(action=action, title=title, note=note, at=at,
                                   in_seconds=in_seconds, repeat_seconds=repeat_seconds,
                                   reminder_id=reminder_id, include_done=include_done,
                                   namespace=namespace)


@server.tool(name="wait_until", description=T.WAIT_UNTIL_SCHEMA["description"])
async def wait_until_tool(request_id: str | None = None, reminder_due: bool = False,
                          at: str | None = None, in_seconds: float | None = None,
                          max_wait: float | None = None, namespace: str | None = None) -> dict:
    return await _toolset.wait_until(request_id=request_id, reminder_due=reminder_due, at=at,
                                     in_seconds=in_seconds, max_wait=max_wait, namespace=namespace)


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraAgent MCP server")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
