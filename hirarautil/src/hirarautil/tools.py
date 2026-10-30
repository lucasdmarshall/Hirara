"""The tool layer: schema and JSON-ready results.

Tools: ``decode``, ``hash``, ``jwt_inspect``, ``jwt_decode``, ``time_now``,
``date_calc``, ``schema_validate``.
"""

from __future__ import annotations

from hirara_core.policy import tool_permission, visible_schemas

import logging
from dataclasses import dataclass

from .config import UtilConfig
from .decode import DecodeError, decode as run_decode
from .decode import result_to_dict as decode_result_to_dict
from .hashing import HashError, hash_input
from .hashing import result_to_dict as hash_result_to_dict
from .jwt import JwtError, jwt_decode as run_jwt_decode
from .jwt import jwt_inspect as run_jwt_inspect
from .jwt import decode_result_to_dict as jwt_decode_result_to_dict
from .jwt import inspect_result_to_dict as jwt_inspect_result_to_dict

from .schema import SchemaError, schema_validate as run_schema_validate
from .timecalc import TimeError, date_calc as run_date_calc, time_now as run_time_now

log = logging.getLogger(__name__)


SYMBOLIC_MATH_SCHEMA = {'name': 'symbolic_math',
 'description': 'Bounded Rust symbolic math: simplify, differentiate (order 1..3), evaluate with '
                'variable bindings, or solve one-variable linear/quadratic equations over the '
                'reals. Use explicit multiplication and nonnegative integer powers (0..32). '
                'Functions include sin, cos, tan, exp, ln, sqrt. f64 precision; original domain '
                'restrictions still apply. No executable code.',
 'input_schema': {'type': 'object',
                  'properties': {'operation': {'type': 'string',
                                               'enum': ['simplify',
                                                        'differentiate',
                                                        'evaluate',
                                                        'solve']},
                                 'expression': {'type': 'string', 'maxLength': 1024},
                                 'variable': {'type': 'string'},
                                 'variables': {'type': 'object',
                                               'additionalProperties': {'type': 'number'}},
                                 'order': {'type': 'integer', 'minimum': 1, 'maximum': 3}},
                  'required': ['operation', 'expression'],
                  'additionalProperties': False}}

JSON_QUERY_SCHEMA = {
    "name": "json_query",
    "description": "Query a JSON value or JSON string using JMESPath (filters, projections, functions) or RFC 6901 JSON Pointer. No code execution, files or network. Output is capped; narrow the query if too large. JMESPath missing keys return null; missing JSON Pointers return an error.",
    "input_schema": {"type": "object", "properties": {
        "input": {"description": "JSON value, or a string containing serialized JSON."},
        "expression": {"type": "string", "maxLength": 4096},
        "syntax": {"type": "string", "enum": ["jmespath", "pointer"], "default": "jmespath"}},
        "required": ["input", "expression"], "additionalProperties": False}}

DECODE_SCHEMA = {
    "name": "decode",
    "description": (
        "Decode a string from a common encoding: base64, base64url, hex, "
        "url (percent-encoding), html entities, or unicode_escape. "
        "format=auto tries to detect. Binary results return as base64 "
        "(output_encoding=base64). Errors stay in the JSON envelope."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "Encoded string to decode.",
            },
            "format": {
                "type": "string",
                "enum": [
                    "auto",
                    "base64",
                    "base64url",
                    "hex",
                    "url",
                    "html",
                    "unicode_escape",
                ],
                "description": "Encoding to apply (default auto).",
            },
        },
        "required": ["input"],
        "additionalProperties": False,
    },
}


HASH_SCHEMA = {
    "name": "hash",
    "description": (
        "Compute message digests (md5, sha1, sha256, sha512, sha3_*, blake2*). "
        "Pass algorithms as a string, list, or \"all\" for a common set. "
        "Input may be utf-8 text (default), base64, or hex. Digests return as "
        "hex (default) or base64."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "String to hash (text, or encoded bytes).",
            },
            "algorithms": {
                "description": (
                    "Algorithm name, list of names, comma-separated string, "
                    "or \"all\" for md5/sha1/sha256/sha512. Default sha256."
                ),
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "encoding": {
                "type": "string",
                "enum": ["utf-8", "ascii", "latin-1", "base64", "hex"],
                "description": "How to interpret input before hashing (default utf-8).",
            },
            "output_format": {
                "type": "string",
                "enum": ["hex", "base64"],
                "description": "Digest encoding (default hex).",
            },
        },
        "required": ["input"],
        "additionalProperties": False,
    },
}


JWT_INSPECT_SCHEMA = {
    "name": "jwt_inspect",
    "description": (
        "Inspect a JWT without verifying the signature: header fields "
        "(alg/typ/kid), claim keys, and time-claim status (exp/iat/nbf). "
        "Optionally include full claims. Accepts a raw token or Bearer prefix. "
        "Errors stay in the JSON envelope."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "JWT string (optionally with Bearer prefix).",
            },
            "include_claims": {
                "type": "boolean",
                "description": "Include full payload claims (default false).",
            },
        },
        "required": ["input"],
        "additionalProperties": False,
    },
}


JWT_DECODE_SCHEMA = {
    "name": "jwt_decode",
    "description": (
        "Decode a JWT header and payload to JSON. Optional HS256/HS384/HS512 "
        "verification when verify=true and secret is provided. Does not verify "
        "asymmetric algorithms. Errors stay in the JSON envelope."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "JWT string (optionally with Bearer prefix).",
            },
            "verify": {
                "type": "boolean",
                "description": "Verify HMAC signature when true (default false).",
            },
            "secret": {
                "type": "string",
                "description": "HMAC secret; required when verify=true.",
            },
            "include_signature": {
                "type": "boolean",
                "description": "Include raw signature segment (default false).",
            },
        },
        "required": ["input"],
        "additionalProperties": False,
    },
}


TIME_NOW_SCHEMA = {
    "name": "time_now",
    "description": (
        "The current date and time. You do not know today's date; call this "
        "whenever the answer depends on it (deadlines, ages, 'next Friday', "
        "opening hours). Give IANA time zones (e.g. Asia/Yangon, "
        "America/New_York); default UTC. Returns weekday, ISO week, UTC offset "
        "and DST for each."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "timezones": {
                "description": "One IANA zone or a list (default UTC).",
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            },
        },
        "additionalProperties": False,
    },
}


DATE_CALC_SCHEMA = {
    "name": "date_calc",
    "description": (
        "Calendar arithmetic without mistakes. operation=add (years, months, "
        "weeks, days, hours, minutes, seconds, business_days; month ends and "
        "DST handled), diff (between date and other: calendar y/m/d, total "
        "days, business days), convert (date into to_timezones), info "
        "(weekday, ISO week, quarter, leap year, month bounds, business day). "
        "Dates are ISO 8601, a unix timestamp, or now / today / tomorrow / "
        "yesterday, read in timezone (default UTC). Business days skip the "
        "weekend (default Sat/Sun) and any holidays listed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["add", "diff", "convert", "info"]},
            "date": {"type": "string", "description": "Start date (default now)."},
            "other": {"type": "string", "description": "Second date for diff."},
            "timezone": {"type": "string", "description": "Zone to read and show dates in."},
            "to_timezones": {
                "description": "Target zone(s) for convert.",
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            },
            "years": {"type": "integer"},
            "months": {"type": "integer"},
            "weeks": {"type": "integer"},
            "days": {"type": "number"},
            "hours": {"type": "number"},
            "minutes": {"type": "number"},
            "seconds": {"type": "number"},
            "business_days": {"type": "integer"},
            "holidays": {"type": "array", "items": {"type": "string"},
                         "description": "ISO dates that are not business days."},
            "weekend": {"type": "array", "items": {"type": "string"},
                        "description": "Weekend days (default Saturday, Sunday)."},
        },
        "required": ["operation"],
        "additionalProperties": False,
    },
}


SCHEMA_VALIDATE_SCHEMA = {
    "name": "schema_validate",
    "description": (
        "Validate JSON against a JSON Schema (draft from $schema, default "
        "2020-12) and list every error with its JSON pointer path, so you can "
        "fix generated output before sending it on. Pass instance and schema "
        "as JSON values or as JSON strings."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "instance": {"description": "The JSON to check (value or JSON string)."},
            "schema": {"description": "The JSON Schema (object or JSON string)."},
            "check_formats": {"type": "boolean",
                              "description": "Also check format (email, date, uri, ...). Default true."},
            "max_errors": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "required": ["instance", "schema"],
        "additionalProperties": False,
    },
}


def _decode_envelope(**overrides) -> dict:
    envelope = {
        "input": None,
        "format": None,
        "detected_format": None,
        "output": None,
        "output_encoding": None,
        "is_binary": None,
        "input_chars": None,
        "output_bytes": None,
        "truncated": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _hash_envelope(**overrides) -> dict:
    envelope = {
        "input": None,
        "input_encoding": None,
        "input_chars": None,
        "input_bytes": None,
        "algorithms": [],
        "digests": {},
        "digest": None,
        "algorithm": None,
        "output_format": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _jwt_inspect_envelope(**overrides) -> dict:
    envelope = {
        "input": None,
        "input_chars": None,
        "segment_count": None,
        "signed": None,
        "algorithm": None,
        "typ": None,
        "kid": None,
        "header": {},
        "claim_keys": [],
        "claims": None,
        "exp": None,
        "iat": None,
        "nbf": None,
        "expired": None,
        "not_yet_valid": None,
        "seconds_to_expiry": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _jwt_decode_envelope(**overrides) -> dict:
    envelope = {
        "input": None,
        "input_chars": None,
        "segment_count": None,
        "signed": None,
        "header": {},
        "payload": {},
        "signature": None,
        "algorithm": None,
        "verified": None,
        "verify_attempted": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Utility tools sharing one config."""

    config: UtilConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=UtilConfig.from_env())

    @visible_schemas
    def schemas(self) -> list[dict]:
        return [JSON_QUERY_SCHEMA, DECODE_SCHEMA, HASH_SCHEMA, JWT_INSPECT_SCHEMA, JWT_DECODE_SCHEMA,
                SYMBOLIC_MATH_SCHEMA, TIME_NOW_SCHEMA, DATE_CALC_SCHEMA, SCHEMA_VALIDATE_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.4.0",
            "tools": list(TOOL_NAMES),
            "max_input_chars": self.config.max_input_chars,
            "max_output_bytes": self.config.max_output_bytes,
        }

    @tool_permission("symbolic_math")
    async def symbolic_math(self, *, operation: str, expression: str, variable: str = "x", variables: dict[str, float] | None = None, order: int = 1) -> dict:
        from hirara_core.native import native_call
        return await native_call("symbolic_math", operation=operation, expression=expression, variable=variable, variables=variables, order=order)

    @tool_permission("json_query")
    async def json_query(self, *, input, expression: str, syntax: str = "jmespath") -> dict:
        from hirara_core.native import native_call
        return {"result": None, **await native_call(
            "json_query", input=input, expression=expression, syntax=syntax,
            max_input_chars=self.config.max_input_chars,
            max_output_bytes=self.config.max_output_bytes)}

    @tool_permission('decode')
    async def decode(
        self,
        *,
        input: str,
        format: str = "auto",
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                run_decode,
                input,
                format=format,
                config=self.config,
            )
            return decode_result_to_dict(result)
        except DecodeError as exc:
            return _decode_envelope(input=input, format=format, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("decode failed")
            return _decode_envelope(
                input=input,
                format=format,
                error=f"decode failed: {exc}",
            )

    @tool_permission('hash')
    async def hash(
        self,
        *,
        input: str,
        algorithms: list[str] | str | None = None,
        encoding: str | None = None,
        output_format: str | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                hash_input,
                input,
                algorithms=algorithms,
                encoding=encoding,
                output_format=output_format,
                config=self.config,
            )
            return hash_result_to_dict(result)
        except HashError as exc:
            return _hash_envelope(input=input, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("hash failed")
            return _hash_envelope(input=input, error=f"hash failed: {exc}")

    @tool_permission('jwt_inspect')
    async def jwt_inspect(
        self,
        *,
        input: str,
        include_claims: bool = False,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                run_jwt_inspect,
                input,
                include_claims=include_claims,
                config=self.config,
            )
            return jwt_inspect_result_to_dict(result)
        except JwtError as exc:
            return _jwt_inspect_envelope(input=input, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("jwt_inspect failed")
            return _jwt_inspect_envelope(
                input=input, error=f"jwt_inspect failed: {exc}"
            )

    @tool_permission('jwt_decode')
    async def jwt_decode(
        self,
        *,
        input: str,
        verify: bool = False,
        secret: str | None = None,
        include_signature: bool = False,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                run_jwt_decode,
                input,
                verify=verify,
                secret=secret,
                include_signature=include_signature,
                config=self.config,
            )
            return jwt_decode_result_to_dict(result)
        except JwtError as exc:
            return _jwt_decode_envelope(input=input, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("jwt_decode failed")
            return _jwt_decode_envelope(
                input=input, error=f"jwt_decode failed: {exc}"
            )


    @tool_permission('time_now')
    async def time_now(self, *, timezones: list[str] | str | None = None) -> dict:
        try:
            return run_time_now(timezones)
        except TimeError as exc:
            return {"zones": [], "text": None, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("time_now failed")
            return {"zones": [], "text": None, "error": f"time_now failed: {exc}"}

    @tool_permission('date_calc')
    async def date_calc(
        self,
        *,
        operation: str,
        date: str | None = None,
        other: str | None = None,
        timezone: str | None = None,
        to_timezones: list[str] | str | None = None,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: float = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        business_days: int = 0,
        holidays: list[str] | None = None,
        weekend: list[str] | None = None,
    ) -> dict:
        try:
            return run_date_calc(
                operation, date_value=date, other=other, timezone_name=timezone,
                to_timezones=to_timezones, years=years, months=months, weeks=weeks,
                days=days, hours=hours, minutes=minutes, seconds=seconds,
                business_days=business_days, holidays=holidays, weekend=weekend,
            )
        except (TimeError, OverflowError) as exc:
            return {"operation": operation, "result": None, "text": None, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("date_calc failed")
            return {"operation": operation, "result": None, "text": None,
                    "error": f"date_calc failed: {exc}"}

    @tool_permission('schema_validate')
    async def schema_validate(self, *, instance, schema, check_formats: bool = True,
                              max_errors: int = 100) -> dict:
        import asyncio

        try:
            return await asyncio.to_thread(
                run_schema_validate, instance, schema, check_formats=check_formats,
                max_errors=max_errors, max_chars=self.config.max_input_chars)
        except SchemaError as exc:
            return {"valid": None, "errors": [], "error_count": None, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("schema_validate failed")
            return {"valid": None, "errors": [], "error_count": None,
                    "error": f"schema_validate failed: {exc}"}


__all__ = [
    "DECODE_SCHEMA",
    "HASH_SCHEMA",
    "JWT_INSPECT_SCHEMA",
    "JWT_DECODE_SCHEMA",
    "TIME_NOW_SCHEMA",
    "DATE_CALC_SCHEMA",
    "SCHEMA_VALIDATE_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = (
    'symbolic_math',
    "json_query",
    "decode",
    "hash",
    "jwt_inspect",
    "jwt_decode",
    "time_now",
    "date_calc",
    "schema_validate",
)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    if name not in TOOL_NAMES:
        raise KeyError(f"unknown tool: {name}")
    return await getattr(_backend(), name)(**(arguments or {}))


@visible_schemas
def tool_schemas() -> list[dict]:
    return _backend().schemas()
