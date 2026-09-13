"""Shared version-1 dataset manifest; label-free index input, optional real clocks."""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from memotrace_ml.artifacts import absolute, reader
from memotrace_ml.common import JSON, list_value, object_value, read_json, string_value
from memotrace_ml.images import MAX_IMAGE_BYTES

SAFE_INTEGER = 9_007_199_254_740_991


def optional_time(value: JSON) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= SAFE_INTEGER:
        raise ValueError("invalid time")
    return value


@dataclass(frozen=True)
class Item:
    id: str
    path: str
    sha256: str
    byte_length: int
    observed_at_ms: int | None = None
    sequence_id: str | None = None
    sequence_position_ms: int | None = None

    def json(self) -> dict[str, JSON]:
        return {
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "observed_at_ms": self.observed_at_ms,
            "sequence_id": self.sequence_id,
            "sequence_position_ms": self.sequence_position_ms,
        }


def load_items(manifest_path: Path) -> tuple[dict[str, JSON], list[Item]]:
    manifest = read_json(manifest_path)
    if set(manifest) != {"version", "dataset", "items"} or manifest["version"] != "1":
        raise ValueError("invalid manifest")
    dataset = object_value(manifest["dataset"])
    if set(dataset) != {"name", "version", "source", "license"}:
        raise ValueError("invalid dataset")
    for value in dataset.values():
        if not string_value(value):
            raise ValueError("invalid dataset metadata")
    items: list[Item] = []
    seen: set[str] = set()
    root = absolute(manifest_path.parent)
    for raw in list_value(manifest["items"]):
        entry = object_value(raw)
        if set(entry) != {
            "id",
            "path",
            "sha256",
            "byte_length",
            "observed_at_ms",
            "sequence_id",
            "sequence_position_ms",
        }:
            raise ValueError("invalid item fields")
        identity, path = string_value(entry["id"]), string_value(entry["path"])
        if not 1 <= len(identity) <= 256 or identity in seen:
            raise ValueError("invalid or duplicate item ID")
        seen.add(identity)
        relative = PurePosixPath(path)
        if (
            not path
            or "\\" in path
            or relative.is_absolute()
            or ".." in relative.parts
            or str(relative) != path
            or relative.suffix.lower() not in {".jpg", ".jpeg"}
        ):
            raise ValueError("invalid image path")
        image_path = root / path
        digest = string_value(entry["sha256"])
        size = entry["byte_length"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid image digest")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_IMAGE_BYTES:
            raise ValueError("invalid image size")
        with reader(image_path, MAX_IMAGE_BYTES) as source:
            if (
                os.fstat(source.fileno()).st_size != size
                or hashlib.file_digest(source, "sha256").hexdigest() != digest
            ):
                raise ValueError("image integrity mismatch")
        sequence = entry["sequence_id"]
        if sequence is not None and (
            not isinstance(sequence, str) or not 1 <= len(sequence) <= 256
        ):
            raise ValueError("invalid sequence")
        position = optional_time(entry["sequence_position_ms"])
        if (sequence is None) != (position is None):
            raise ValueError("sequence requires position")
        items.append(
            Item(
                identity,
                path,
                digest,
                size,
                optional_time(entry["observed_at_ms"]),
                sequence,
                position,
            )
        )
    return dataset, items
