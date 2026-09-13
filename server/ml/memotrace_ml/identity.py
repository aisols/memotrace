"""Path-free implementation and numerical-runtime content identity."""

import base64
import csv
import hashlib
import importlib.metadata
import os
import platform
import re
import stat
import sys
import sysconfig
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import cast

from memotrace_ml.common import JSON, fingerprint

MAX_DISTRIBUTION_FILES = 20_000
MAX_DISTRIBUTION_BYTES = 2 * 1024 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_IMPLEMENTATION_FILES = 256
MAX_IMPLEMENTATION_BYTES = 8 * 1024 * 1024
MAX_IMPLEMENTATION_ENTRIES = 1024
MAX_IMPLEMENTATION_DEPTH = 64


def _outside_environment_script(path: PurePosixPath) -> bool:
    parts = path.parts
    parent_count = 0
    while parent_count < len(parts) and parts[parent_count] == "..":
        parent_count += 1
    # Wheel installers commonly declare generated entry-point scripts outside
    # site-packages. They are not executed by the module worker and are path-specific.
    return (
        parent_count > 0
        and len(parts) == parent_count + 2
        and parts[parent_count] == "bin"
        and parts[-1] not in {"", ".", ".."}
    )


def _record_descriptor(root: int, path: PurePosixPath) -> int:
    directory = os.dup(root)
    try:
        for part in path.parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            os.close(directory)
            directory = child
        return os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=directory,
        )
    except OSError:
        raise ValueError("installed distribution file is missing or unsafe") from None
    finally:
        os.close(directory)


def _regular_info(descriptor: int, max_bytes: int, error: str) -> os.stat_result:
    try:
        info = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise ValueError(error) from None
    if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= max_bytes:
        os.close(descriptor)
        raise ValueError(error)
    return info


def _record_digest(root: int, path: PurePosixPath, max_bytes: int) -> tuple[int, bytes]:
    descriptor = _record_descriptor(root, path)
    before = _regular_info(
        descriptor, max_bytes, "installed distribution entry is not a bounded regular file"
    )
    with os.fdopen(descriptor, "rb") as source:
        digest = hashlib.file_digest(source, "sha256").digest()
        after = os.fstat(source.fileno())
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise ValueError("installed distribution file changed while hashing")
    return before.st_size, digest


def distribution_record_identity(name: str) -> dict[str, JSON]:
    """Verify and hash RECORD files rooted in the distribution's site directory.

    Installer-generated ``../bin`` entry points are syntax-checked but excluded:
    the module worker does not execute them and their shebang bytes encode install paths.
    """
    distribution = importlib.metadata.distribution(name)
    if not isinstance(distribution, importlib.metadata.PathDistribution):
        raise ValueError("installed distribution must be filesystem-backed")
    try:
        located_root = Path(str(distribution.locate_file(""))).absolute()
        distribution_root = located_root.resolve(strict=True)
        metadata_path = Path(str(distribution._path)).absolute()
        metadata_relative = metadata_path.relative_to(located_root)
        if len(metadata_relative.parts) != 1 or not metadata_relative.name.endswith(".dist-info"):
            raise ValueError("installed distribution metadata path is unsafe")
        record_path = PurePosixPath(metadata_relative.as_posix()) / "RECORD"
        root = os.open(
            distribution_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError:
        raise ValueError("installed distribution root is unavailable") from None
    records: list[JSON] = []
    seen: set[str] = set()
    total_size = 0
    record_entries = 0
    try:
        try:
            descriptor = _record_descriptor(root, record_path)
            info = _regular_info(
                descriptor,
                MAX_RECORD_BYTES,
                "installed distribution RECORD is not a bounded regular file",
            )
            if info.st_size == 0:
                os.close(descriptor)
                raise ValueError("installed distribution RECORD is empty")
            with os.fdopen(descriptor, "rb") as source:
                raw_record = source.read(MAX_RECORD_BYTES + 1)
                after = os.fstat(source.fileno())
            if len(raw_record) != info.st_size or (
                info.st_dev,
                info.st_ino,
                info.st_size,
            ) != (after.st_dev, after.st_ino, after.st_size):
                raise ValueError("installed distribution RECORD changed while reading")
            rows = list(csv.reader(raw_record.decode("utf-8").splitlines(), strict=True))
        except (csv.Error, UnicodeError):
            raise ValueError("malformed installed distribution RECORD") from None
        if not rows or len(rows) > MAX_DISTRIBUTION_FILES or any(len(row) != 3 for row in rows):
            raise ValueError("malformed installed distribution RECORD")
        for relative, declared_hash, size_text in sorted(rows, key=lambda row: row[0]):
            path = PurePosixPath(relative)
            if (
                not relative
                or not path.parts
                or path.is_absolute()
                or "\\" in relative
                or "\0" in relative
                or relative != path.as_posix()
                or relative in seen
            ):
                raise ValueError("invalid installed distribution RECORD path")
            seen.add(relative)
            outside_script = False
            if ".." in path.parts:
                outside_script = _outside_environment_script(path)
                if not outside_script:
                    raise ValueError("invalid installed distribution RECORD path")
            is_record = path == record_path
            if is_record:
                record_entries += 1
                if declared_hash or size_text:
                    raise ValueError("installed distribution RECORD must be unhashed")
                continue
            if not declared_hash or not size_text:
                raise ValueError("installed distribution RECORD entry is unhashed")
            mode, separator, encoded_hash = declared_hash.partition("=")
            if (
                separator != "="
                or mode != "sha256"
                or re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded_hash) is None
                or re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", size_text) is None
            ):
                raise ValueError("malformed installed distribution RECORD entry")
            declared_size = int(size_text)
            if outside_script:
                continue
            size, digest = _record_digest(root, path, MAX_DISTRIBUTION_BYTES - total_size)
            total_size += size
            if total_size > MAX_DISTRIBUTION_BYTES:
                raise ValueError("installed distribution content exceeds identity bound")
            if declared_size != size:
                raise ValueError("installed distribution RECORD metadata mismatch")
            encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            if encoded_hash != encoded:
                raise ValueError("installed distribution RECORD digest mismatch")
            records.append(
                {
                    "path": relative,
                    "sha256": digest.hex(),
                    "byte_length": size,
                }
            )
    finally:
        os.close(root)
    if record_entries != 1:
        raise ValueError("installed distribution RECORD entry is missing or ambiguous")
    return {
        "version": distribution.version,
        "content_sha256": fingerprint(records),
        "file_count": len(records),
        "byte_length": total_size,
    }


def cpu_features(cpuinfo: Path = Path("/proc/cpuinfo")) -> list[str]:
    feature_sets: list[set[str]] = []
    for line in cpuinfo.read_text(encoding="ascii").splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"flags", "Features"}:
            features = set(value.split())
            if not features or any(
                re.fullmatch(r"[A-Za-z0-9_.-]+", item) is None for item in features
            ):
                raise ValueError("invalid CPU feature inventory")
            feature_sets.append(features)
    if not feature_sets:
        raise ValueError("CPU feature inventory unavailable")
    return sorted(set.intersection(*feature_sets))


def numerical_runtime_identity(
    distributions: tuple[str, ...], torch_build: dict[str, JSON]
) -> dict[str, JSON]:
    libc_name, libc_version = platform.libc_ver()
    python_build, python_build_date = platform.python_build()
    return {
        "version": "numerical-runtime-v2",
        "distributions": {name: distribution_record_identity(name) for name in distributions},
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "cache_tag": sys.implementation.cache_tag,
            "abi_flags": sys.abiflags,
            "soabi": str(sysconfig.get_config_var("SOABI")),
            "compiler": platform.python_compiler(),
            "build": python_build,
            "build_date": python_build_date,
        },
        "libc": {"name": libc_name, "version": libc_version},
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "torch_build": torch_build,
        "cpu_features": cast(list[JSON], cpu_features()),
    }


def implementation_files(root: Traversable | None = None) -> dict[str, JSON]:
    result: dict[str, JSON] = {}
    total_size = 0
    visited = 0

    def visit(directory: Traversable, prefix: str) -> None:
        nonlocal total_size, visited
        if prefix.count("/") > MAX_IMPLEMENTATION_DEPTH:
            raise ValueError("implementation source exceeds identity depth bound")
        for entry in sorted(directory.iterdir(), key=lambda entry: entry.name):
            visited += 1
            if visited > MAX_IMPLEMENTATION_ENTRIES:
                raise ValueError("implementation source exceeds identity entry bound")
            if isinstance(entry, Path) and entry.is_symlink():
                raise ValueError("implementation source entry must not be a symlink")
            name = prefix + entry.name
            if entry.is_dir() and entry.name != "__pycache__":
                visit(entry, name + "/")
            elif entry.is_file() and entry.name.endswith(".py"):
                remaining = MAX_IMPLEMENTATION_BYTES - total_size
                with entry.open("rb") as source:
                    raw = source.read(remaining + 1)
                total_size += len(raw)
                if len(result) >= MAX_IMPLEMENTATION_FILES or total_size > MAX_IMPLEMENTATION_BYTES:
                    raise ValueError("implementation source exceeds identity bound")
                result[name] = hashlib.sha256(raw).hexdigest()

    visit(root if root is not None else files("memotrace_ml"), "")
    if not result:
        raise ValueError("implementation source bytes unavailable")
    return result


def implementation_digest(root: Traversable | None = None) -> str:
    return fingerprint(implementation_files(root))


def fingerprint_with_implementation(
    settings: dict[str, JSON],
    root: Traversable | None = None,
) -> tuple[dict[str, JSON], str]:
    sources = implementation_files(root)
    identity: dict[str, JSON] = {
        **settings,
        "implementation_sha256": fingerprint(sources),
        "implementation_files": sources,
    }
    return identity, fingerprint(identity)
