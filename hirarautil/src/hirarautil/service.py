"""HTTP front end.

    uvicorn hirarautil.service:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

from hirara_core.policy import install_backend

import logging

from fastapi import FastAPI
from typing import Any

from pydantic import BaseModel, Field

from .tools import Toolset

log = logging.getLogger("hirarautil.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarautil", version="0.3.0")

install_backend(app)


class DecodeRequest(BaseModel):
    """JSON body for decode."""

    input: str
    format: str = "auto"


class HashRequest(BaseModel):
    """JSON body for hash."""

    input: str
    algorithms: list[str] | str | None = None
    encoding: str | None = None
    output_format: str | None = None


class JwtInspectRequest(BaseModel):
    """JSON body for jwt_inspect."""

    input: str
    include_claims: bool = False


class JwtDecodeRequest(BaseModel):
    """JSON body for jwt_decode."""

    input: str
    verify: bool = False
    secret: str | None = None
    include_signature: bool = False


class TimeNowRequest(BaseModel):
    """JSON body for time_now."""

    timezones: list[str] | str | None = None


class DateCalcRequest(BaseModel):
    """JSON body for date_calc."""

    operation: str
    date: str | None = None
    other: str | None = None
    timezone: str | None = None
    to_timezones: list[str] | str | None = None
    years: int = 0
    months: int = 0
    weeks: int = 0
    days: float = 0
    hours: float = 0
    minutes: float = 0
    seconds: float = 0
    business_days: int = 0
    holidays: list[str] | None = None
    weekend: list[str] | None = None


class SchemaValidateRequest(BaseModel):
    """JSON body for schema_validate."""

    instance: Any = None
    # "schema" would shadow a BaseModel attribute; the JSON key is still "schema".
    schema_: Any = Field(None, alias="schema")
    check_formats: bool = True
    max_errors: int = 100

    model_config = {"populate_by_name": True}


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/decode")
async def decode_endpoint(request: DecodeRequest) -> dict:
    return await _toolset.decode(input=request.input, format=request.format)


@app.post("/hash")
async def hash_endpoint(request: HashRequest) -> dict:
    return await _toolset.hash(
        input=request.input,
        algorithms=request.algorithms,
        encoding=request.encoding,
        output_format=request.output_format,
    )


@app.post("/jwt_inspect")
async def jwt_inspect_endpoint(request: JwtInspectRequest) -> dict:
    return await _toolset.jwt_inspect(
        input=request.input,
        include_claims=request.include_claims,
    )


@app.post("/jwt_decode")
async def jwt_decode_endpoint(request: JwtDecodeRequest) -> dict:
    return await _toolset.jwt_decode(
        input=request.input,
        verify=request.verify,
        secret=request.secret,
        include_signature=request.include_signature,
    )


@app.post("/time_now")
async def time_now_endpoint(request: TimeNowRequest) -> dict:
    return await _toolset.time_now(timezones=request.timezones)


@app.post("/date_calc")
async def date_calc_endpoint(request: DateCalcRequest) -> dict:
    return await _toolset.date_calc(**request.model_dump())


@app.post("/schema_validate")
async def schema_validate_endpoint(request: SchemaValidateRequest) -> dict:
    return await _toolset.schema_validate(
        instance=request.instance,
        schema=request.schema_,
        check_formats=request.check_formats,
        max_errors=request.max_errors,
    )


class JsonQueryRequest(BaseModel):
    input: object
    expression: str
    syntax: str = "jmespath"


@app.post("/json_query")
async def json_query_endpoint(request: JsonQueryRequest) -> dict:
    return await _toolset.json_query(**request.model_dump())
