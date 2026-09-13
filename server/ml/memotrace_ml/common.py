"""Small typed JSON and artifact boundary helpers."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import cast

from memotrace_ml.artifacts import absolute, digest, ensure_directory, read_bytes, write_once
from memotrace_ml.numbers import ExactDecimal, parse_decimal

type JSON = None | bool | int | float | Decimal | ExactDecimal | str | list[JSON] | dict[str, JSON]


def canonical(value: JSON) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except TypeError:
        # Rare exact-decimal request/diagnostic serialization; ordinary vectors use
        # the fast standard encoder. Decimal numbers remain JSON numbers, not strings.
        if isinstance(value, Decimal | ExactDecimal):
            token = value.lexeme if isinstance(value, ExactDecimal) else str(value)
            ExactDecimal.parse(token)
            return token.encode("ascii")
        if isinstance(value, list):
            return b"[" + b",".join(canonical(item) for item in value) + b"]"
        if isinstance(value, dict):
            return (
                b"{"
                + b",".join(canonical(key) + b":" + canonical(value[key]) for key in sorted(value))
                + b"}"
            )
        raise


def fingerprint(value: JSON) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def object_value(value: JSON) -> dict[str, JSON]:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def string_value(value: JSON) -> str:
    if not isinstance(value, str):
        raise ValueError("expected string")
    return value


def list_value(value: JSON) -> list[JSON]:
    if not isinstance(value, list):
        raise ValueError("expected list")
    return value


def no_duplicates(pairs: list[tuple[str, JSON]]) -> dict[str, JSON]:
    result: dict[str, JSON] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError("nonfinite JSON")


def parse_json(raw: bytes, *, exact_numbers: bool = False) -> JSON:
    return cast(
        JSON,
        json.loads(
            raw,
            object_pairs_hook=no_duplicates,
            parse_constant=invalid_constant,
            parse_float=parse_decimal if exact_numbers else float,
        ),
    )


def read_json(path: Path) -> dict[str, JSON]:
    return object_value(parse_json(read_bytes(path)))


def write_json(path: Path, value: JSON) -> None:
    write_once(path, canonical(value) + b"\n")


def file_digest(path: Path) -> str:
    return digest(path)


def external_root(path: Path) -> Path:
    root = absolute(path)
    # Artifacts must be outside any checkout, including an enclosing worktree.
    for parent in (root, *root.parents):
        if (parent / ".git").exists():
            raise ValueError("artifact root must be outside Git")
    ensure_directory(root)
    return root
