"""schema_validate: check JSON against a JSON Schema and report every error.

An agent that produced JSON for another system needs to know whether it
conforms, and if not, exactly where and why, so it can fix the output
instead of guessing. Uses the reference ``jsonschema`` implementation;
the draft comes from ``$schema`` (default 2020-12).
"""

from __future__ import annotations

import json

from jsonschema import exceptions as js_exceptions
from jsonschema import validators

MAX_ERRORS = 100


class SchemaError(ValueError):
    """Caller-facing schema_validate failure."""


def _load(value, what: str, max_chars: int):
    if isinstance(value, str):
        if len(value) > max_chars:
            raise SchemaError(f"{what} is longer than {max_chars} characters")
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{what} is not valid JSON: {exc.msg} at line {exc.lineno} "
                              f"column {exc.colno}") from exc
    return value


def _pointer(parts) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts) if parts else ""


def schema_validate(instance, schema, *, check_formats: bool = True,
                    max_errors: int = MAX_ERRORS, max_chars: int = 2_000_000) -> dict:
    if schema is None:
        raise SchemaError("schema is required")
    data = _load(instance, "instance", max_chars)
    spec = _load(schema, "schema", max_chars)
    if not isinstance(spec, (dict, bool)):
        raise SchemaError("schema must be a JSON object (or true / false)")

    cls = validators.validator_for(spec, default=validators.Draft202012Validator)
    try:
        cls.check_schema(spec)
    except js_exceptions.SchemaError as exc:
        raise SchemaError(f"the schema itself is invalid at {_pointer(exc.absolute_path) or '/'}: "
                          f"{exc.message}") from exc
    kwargs = {"format_checker": cls.FORMAT_CHECKER} if check_formats else {}
    validator = cls(spec, **kwargs)

    errors = []
    total = 0
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        total += 1
        if len(errors) < max(1, min(int(max_errors), 1000)):
            errors.append({
                "path": _pointer(err.absolute_path),
                "message": err.message,
                "validator": err.validator,
                "schema_path": _pointer(err.absolute_schema_path),
            })
    lines = [f"{'valid' if not total else f'{total} error(s)'} ({cls.__name__})"]
    lines += [f"{e['path'] or '/'}: {e['message']}" for e in errors[:20]]
    return {
        "valid": total == 0,
        "error_count": total,
        "errors": errors,
        "draft": cls.__name__.replace("Validator", ""),
        "text": "\n".join(lines),
        "error": None,
    }


__all__ = ["SchemaError", "schema_validate"]
