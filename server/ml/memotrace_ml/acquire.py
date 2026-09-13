"""Explicit, confined public model acquisition. Never imported by inference."""

import argparse
import hashlib
import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypedDict

from memotrace_ml.artifacts import entries, publish, reader, staging
from memotrace_ml.checkpoints import APPROVED_MODEL_IDS, DEFAULT_CHECKPOINT, pinned_manifest
from memotrace_ml.common import (
    JSON,
    external_root,
    object_value,
    string_value,
    write_json,
)
from memotrace_ml.public_download import bounded_fetch, public_url


class DownloadReceipt(TypedDict):
    source: str
    sha256: str
    byte_length: int


def receipt_json(receipt: DownloadReceipt) -> dict[str, JSON]:
    return {
        "source": receipt["source"],
        "sha256": receipt["sha256"],
        "byte_length": receipt["byte_length"],
    }


def validate_body(fd: int, max_bytes: int, validate: Callable[[bytes], None]) -> None:
    with os.fdopen(os.dup(fd), "rb") as source:
        source.seek(0)
        body = source.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("artifact exceeds validation bound")
    validate(body)


def descriptor_digest(fd: int, algorithm: str) -> str:
    with os.fdopen(os.dup(fd), "rb") as source:
        source.seek(0)
        return hashlib.file_digest(source, algorithm).hexdigest()


def download(
    url: str,
    target: Path,
    max_bytes: int,
    expected: str | None = None,
    seconds: float = 600,
    expected_length: int | None = None,
    expected_md5: str | None = None,
    validate: Callable[[bytes], None] | None = None,
) -> DownloadReceipt:
    """Existing files require an independently pinned or durable acquisition hash."""
    public_url(url)
    if expected_md5 is not None and re.fullmatch(r"[0-9a-f]{32}", expected_md5) is None:
        raise ValueError("invalid expected MD5")
    try:
        with reader(target, max_bytes) as source:
            if expected is None:
                raise ValueError("unverified existing artifact")
            size = os.fstat(source.fileno()).st_size
            digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest != expected or (expected_length is not None and size != expected_length):
                raise ValueError("existing artifact mismatch")
            if (
                expected_md5 is not None
                and descriptor_digest(source.fileno(), "md5") != expected_md5
            ):
                raise ValueError("existing artifact MD5 mismatch")
            if validate is not None:
                validate_body(source.fileno(), max_bytes, validate)
            return {"source": url, "sha256": digest, "byte_length": size}
    except FileNotFoundError:
        pass
    with staging(target) as (fd, parent, stage):
        receipt = bounded_fetch(url, fd, max_bytes, seconds)
        digest = string_value(receipt["sha256"])
        download_size = receipt["byte_length"]
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or isinstance(download_size, bool)
            or not isinstance(download_size, int)
            or not 0 <= download_size <= max_bytes
        ):
            raise ValueError("invalid download receipt")
        if expected is not None and digest != expected:
            raise ValueError("artifact digest mismatch")
        if expected_length is not None and download_size != expected_length:
            raise ValueError("artifact length mismatch")
        if expected_md5 is not None and descriptor_digest(fd, "md5") != expected_md5:
            raise ValueError("artifact MD5 mismatch")
        if validate is not None:
            # Eligibility is decided while the downloader still owns the stage.
            # Rejection removes only this exclusive stage, never a published file.
            validate_body(fd, max_bytes, validate)
        publish(fd, parent, stage, target.name)
    return {"source": url, "sha256": digest, "byte_length": download_size}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument(
        "--model-id",
        choices=APPROVED_MODEL_IDS,
        default=DEFAULT_CHECKPOINT.model_id,
    )
    args = parser.parse_args(argv)
    root = external_root(args.model_dir)
    manifest = pinned_manifest(args.model_id)
    model_id = string_value(manifest["model_id"])
    revision = string_value(manifest["revision"])
    for name, entry in object_value(manifest["files"]).items():
        meta = object_value(entry)
        size = meta["byte_length"]
        if not isinstance(size, int):
            raise ValueError("invalid pinned size")
        download(
            f"https://huggingface.co/{model_id}/resolve/{revision}/{name}?download=true",
            root / name,
            size,
            string_value(meta["sha256"]),
            seconds=1800,
            expected_length=size,
        )
        print(f"verified {name}", flush=True)
    write_json(root / "manifest.json", manifest)
    if set(entries(root)) != {*object_value(manifest["files"]), "manifest.json"}:
        raise ValueError("unexpected model artifact")
    print(f"verified model directory: {root}")


if __name__ == "__main__":
    main()
