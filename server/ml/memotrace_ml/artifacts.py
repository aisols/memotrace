"""Linux descriptor-relative artifact I/O: no symlink traversal or clobbering."""

import hashlib
import io
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def absolute(path: Path) -> Path:
    if ".." in path.parts:
        raise ValueError("parent traversal is forbidden")
    return Path(os.path.abspath(path))


def _trusted_owner_mode(info: os.stat_result, kind: str) -> None:
    if info.st_uid != os.geteuid():
        raise ValueError(f"{kind} must be owned by the effective user")
    if info.st_mode & 0o022:
        raise ValueError(f"{kind} must not be group or other writable")


def _trusted_directory(info: os.stat_result, *, final: bool) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("artifact path component must be a directory")
    if final:
        _trusted_owner_mode(info, "artifact directory")
    elif info.st_mode & 0o022 and not (
        info.st_mode & stat.S_ISVTX and info.st_uid in {0, os.geteuid()}
    ):
        # Root-owned sticky /tmp is a safe traversal ancestor: another user cannot
        # replace this user's child. Ordinary writable ancestors are not trusted.
        raise ValueError("artifact directory ancestry is writable")


@contextmanager
def directory(path: Path, *, create: bool = False) -> Iterator[int]:
    """Walk trusted directories with O_NOFOLLOW; retain the final dirfd."""
    path = absolute(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        parts = path.parts[1:]
        _trusted_directory(os.fstat(fd), final=not parts)
        for index, part in enumerate(parts):
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            _trusted_directory(os.fstat(fd), final=index == len(parts) - 1)
        yield fd
    finally:
        os.close(fd)


def ensure_directory(path: Path) -> None:
    with directory(path, create=True):
        pass


def entries(path: Path) -> list[str]:
    with directory(path) as fd:
        return sorted(os.listdir(fd))


@contextmanager
def reader(path: Path, max_bytes: int | None = None) -> Iterator[io.BufferedReader]:
    with directory(path.parent) as parent:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
        )
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("artifact must be a regular file")
        _trusted_owner_mode(info, "artifact file")
        if max_bytes is not None and info.st_size > max_bytes:
            raise ValueError("artifact exceeds size bound")
        yield source


def read_bytes(path: Path, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    with reader(path, max_bytes) as source:
        result = source.read(max_bytes + 1)
    if len(result) > max_bytes:
        raise ValueError("artifact exceeds size bound")
    return result


def digest(path: Path) -> str:
    with reader(path) as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


@contextmanager
def staging(target: Path) -> Iterator[tuple[int, int, str]]:
    """An exclusive unpredictable stage in an already-verified directory."""
    with directory(target.parent) as parent:
        name = ".memotrace-stage-" + secrets.token_hex(16)
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        try:
            yield fd, parent, name
        finally:
            os.close(fd)
            os.unlink(name, dir_fd=parent)


def publish(fd: int, parent: int, stage: str, target: str) -> None:
    """linkat provides atomic no-clobber publication on the same filesystem."""
    os.fsync(fd)
    os.link(stage, target, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
    os.fsync(parent)


def write_once(path: Path, data: bytes) -> None:
    """Existing identical files are retained; different bytes or symlinks fail."""
    try:
        existing = read_bytes(path, len(data))
    except FileNotFoundError:
        pass
    else:
        if existing != data:
            raise ValueError("existing artifact differs; choose a new destination")
        return
    with staging(path) as (fd, parent, name):
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(data)
        publish(fd, parent, name, path.name)
