"""HTTP front end.

    uvicorn hirarafs.service:app --host 0.0.0.0 --port 8900

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Mount a workspace
volume and set CFS_ROOTS when running in Docker.
"""

from __future__ import annotations

from hirara_core.policy import install_backend

import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hirarafs.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarafs", version="0.3.0")

install_backend(app)


class FileReadRequest(BaseModel):
    """JSON body for file_read."""

    path: str
    encoding: str | None = None
    max_bytes: int | None = None
    offset: int = 0


class FileWriteRequest(BaseModel):
    """JSON body for file_write."""

    path: str
    content: str
    encoding: str | None = None
    append: bool = False
    create_parents: bool = False
    overwrite: bool = True
    max_bytes: int | None = None


class FileEditRequest(BaseModel):
    """JSON body for file_edit."""

    path: str
    old_string: str | None = None
    new_string: str | None = None
    replace_all: bool = False
    edits: list[dict] | None = None
    dry_run: bool = False


class FileSearchRequest(BaseModel):
    """JSON body for file_search."""

    pattern: str
    path: str | None = None
    glob: str | None = None
    regex: bool = True
    case_sensitive: bool = False
    context: int = 0
    max_results: int = 200
    include_hidden: bool = False


class FileListRequest(BaseModel):
    """JSON body for file_list."""

    path: str | None = None
    pattern: str | None = None
    recursive: bool = False
    include_hidden: bool = False
    max_entries: int = 500


class ArchiveListRequest(BaseModel):
    """JSON body for archive_list."""

    path: str
    max_entries: int = 1000


class ArchiveExtractRequest(BaseModel):
    """JSON body for archive_extract."""

    path: str
    dest: str
    members: list[str] | None = None
    overwrite: bool = False


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/file_read")
async def file_read_endpoint(request: FileReadRequest) -> dict:
    # Errors come back in the body, not as HTTP status codes: the caller is an
    # agent loop, and "file not found" is a result to reason about.
    return await _toolset.file_read(
        path=request.path,
        encoding=request.encoding,
        max_bytes=request.max_bytes,
        offset=request.offset,
    )


@app.post("/file_write")
async def file_write_endpoint(request: FileWriteRequest) -> dict:
    return await _toolset.file_write(
        path=request.path,
        content=request.content,
        encoding=request.encoding,
        append=request.append,
        create_parents=request.create_parents,
        overwrite=request.overwrite,
        max_bytes=request.max_bytes,
    )


@app.post("/file_edit")
async def file_edit_endpoint(request: FileEditRequest) -> dict:
    return await _toolset.file_edit(**request.model_dump())


@app.post("/file_search")
async def file_search_endpoint(request: FileSearchRequest) -> dict:
    return await _toolset.file_search(**request.model_dump())


@app.post("/file_list")
async def file_list_endpoint(request: FileListRequest) -> dict:
    return await _toolset.file_list(**request.model_dump())


@app.post("/archive_list")
async def archive_list_endpoint(request: ArchiveListRequest) -> dict:
    return await _toolset.archive_list(**request.model_dump())


@app.post("/archive_extract")
async def archive_extract_endpoint(request: ArchiveExtractRequest) -> dict:
    return await _toolset.archive_extract(**request.model_dump())


class FileCopyRequest(BaseModel):
    path: str
    dest: str
    overwrite: bool = False


@app.post("/file_copy")
async def file_copy_endpoint(request: FileCopyRequest) -> dict:
    return await _toolset.file_copy(**request.model_dump())


class FileMoveRequest(BaseModel):
    path: str
    dest: str
    overwrite: bool = False


@app.post("/file_move")
async def file_move_endpoint(request: FileMoveRequest) -> dict:
    return await _toolset.file_move(**request.model_dump())


class FileRenameRequest(BaseModel):
    path: str
    name: str
    overwrite: bool = False


@app.post("/file_rename")
async def file_rename_endpoint(request: FileRenameRequest) -> dict:
    return await _toolset.file_rename(**request.model_dump())


class FileDeleteRequest(BaseModel):
    path: str


@app.post("/file_delete")
async def file_delete_endpoint(request: FileDeleteRequest) -> dict:
    return await _toolset.file_delete(**request.model_dump())
