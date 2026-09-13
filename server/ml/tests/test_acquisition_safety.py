"""Offline reproductions of redirects, trickles, confinement and provenance drift."""

import base64
import csv
import hashlib
import io
import os
import socket
import ssl
import time
from pathlib import Path

import pytest
from PIL import Image

from memotrace_ml import openimages, public_download
from memotrace_ml.acquire import download
from memotrace_ml.artifacts import ensure_directory, entries, read_bytes
from memotrace_ml.common import (
    JSON,
    file_digest,
    fingerprint,
    list_value,
    object_value,
    read_json,
    write_json,
)
from memotrace_ml.dataset import Item, load_items
from memotrace_ml.images import MAX_IMAGE_BYTES
from memotrace_ml.openimages import (
    BUCKET,
    CLASS_PROFILE,
    CLASS_PROFILE_ID,
    CLASS_PROFILE_VERSION,
    CLASSES,
    DATASET_NAME,
    DATASET_VERSION_PREFIX,
    IMAGE_BUCKET,
    LICENSE,
    METADATA,
    SELECTION_VERSION,
    SOURCE,
    class_profile,
    prepare,
    round_robin_candidates,
    validate_acquisition_profile,
    validate_attribution,
    verified_acquisition,
)


@pytest.mark.parametrize(
    "location",
    [
        "http://huggingface.co/file",
        "https://127.0.0.1/file",
        "https://169.254.169.254/file",
        "https://[::1]/file",
        "https://private.invalid/file",
        "https://huggingface.co:444/file",
        "https://user:password@huggingface.co/file",
        "https://huggingface.co.evil.invalid/file",
    ],
)
def test_forbidden_redirect_rejected_before_next_dns_or_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    hosts: list[str] = []
    addresses: list[public_download.Address] = [
        (socket.AF_INET, ("8.8.8.8", 443)),
        (socket.AF_INET, ("8.8.4.4", 443)),
    ]
    attempted: list[public_download.Address] = []
    responses_closed: list[public_download.Address] = []
    connections_closed: list[public_download.Address] = []

    def resolve(host: str) -> list[public_download.Address]:
        hosts.append(host)
        return addresses

    class Redirect:
        status = 302

        def __init__(self, address: public_download.Address) -> None:
            self.address = address

        def getheader(self, name: str) -> str:
            assert name == "Location"
            return location

        def close(self) -> None:
            responses_closed.append(self.address)

    class FakeHTTPS:
        def __init__(self, host: str, address: public_download.Address) -> None:
            assert host == "huggingface.co"
            self.address = address

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            attempted.append(self.address)

        def getresponse(self) -> Redirect:
            return Redirect(self.address)

        def close(self) -> None:
            connections_closed.append(self.address)

    monkeypatch.setattr(public_download, "public_addresses", resolve)
    monkeypatch.setattr(public_download, "PinnedHTTPSConnection", FakeHTTPS)
    with (tmp_path / "stage").open("wb") as stage, pytest.raises(ValueError):
        public_download.fetch("https://huggingface.co/file", stage.fileno(), 100)
    assert hosts == ["huggingface.co"]
    assert attempted == responses_closed == connections_closed == addresses[:1]


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "224.0.0.1"]
)
def test_allowlisted_host_with_private_dns_fails_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    def answer(*args: object, **kwargs: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", answer)
    with pytest.raises(ValueError, match="non-public"):
        public_download.public_addresses("huggingface.co")


def test_dns_address_is_pinned_and_tls_hostname_verification_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected: list[object] = []

    class FakeSocket:
        def settimeout(self, value: float) -> None:
            pass

        def connect(self, address: object) -> None:
            connected.append(address)

        def close(self) -> None:
            pass

    connection = public_download.PinnedHTTPSConnection(
        "huggingface.co", (socket.AF_INET, ("8.8.8.8", 443))
    )
    # Inspect the actual verification context, without performing a TLS connection.
    assert connection.tls_context.check_hostname
    assert connection.tls_context.verify_mode == ssl.CERT_REQUIRED

    def wrap(raw: object, *, server_hostname: str) -> object:
        connected.append(server_hostname)
        return raw

    monkeypatch.setattr(connection.tls_context, "wrap_socket", wrap)
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: FakeSocket())
    connection.connect()
    assert connected == [("8.8.8.8", 443), "huggingface.co"]


def test_download_fails_over_to_later_validated_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addresses: list[public_download.Address] = [
        (socket.AF_INET, ("8.8.8.8", 443)),
        (socket.AF_INET, ("8.8.4.4", 443)),
    ]
    attempted: list[public_download.Address] = []
    responses_closed: list[public_download.Address] = []
    connections_closed: list[public_download.Address] = []
    body = b"synthetic public bytes"

    class Response:
        status = 200

        def __init__(self) -> None:
            self.remaining = body

        def getheader(self, name: str) -> str | None:
            return str(len(body)) if name == "Content-Length" else None

        def read(self, _size: int) -> bytes:
            chunk, self.remaining = self.remaining, b""
            return chunk

        def close(self) -> None:
            responses_closed.append(addresses[1])

    class FakeHTTPS:
        def __init__(self, host: str, address: public_download.Address) -> None:
            assert host == "huggingface.co"
            self.address = address

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            attempted.append(self.address)
            if self.address == addresses[0]:
                raise OSError("unreachable test address")

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            connections_closed.append(self.address)

    monkeypatch.setattr(public_download, "public_addresses", lambda _host: addresses)
    monkeypatch.setattr(public_download, "PinnedHTTPSConnection", FakeHTTPS)
    target = tmp_path / "download"
    with target.open("wb") as destination:
        receipt = public_download.fetch(
            "https://huggingface.co/file", destination.fileno(), len(body)
        )
    assert attempted == addresses
    assert responses_closed == addresses[1:]
    assert connections_closed == addresses
    assert target.read_bytes() == body
    assert receipt == {"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}


@pytest.mark.parametrize("malformed", ["missing-location", "content-length"])
def test_download_malformed_response_metadata_fails_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: str
) -> None:
    addresses: list[public_download.Address] = [
        (socket.AF_INET, ("8.8.8.8", 443)),
        (socket.AF_INET, ("8.8.4.4", 443)),
    ]
    attempted: list[public_download.Address] = []
    responses_closed: list[public_download.Address] = []
    connections_closed: list[public_download.Address] = []
    body = b"valid fallback body"

    class Response:
        def __init__(self, address: public_download.Address) -> None:
            self.address = address
            self.status = (
                302 if address == addresses[0] and malformed == "missing-location" else 200
            )
            self.remaining = body

        def getheader(self, name: str) -> str | None:
            if name == "Location":
                return None
            if name == "Content-Length" and self.address == addresses[0]:
                return "not-an-integer"
            return str(len(body)) if name == "Content-Length" else None

        def read(self, _size: int) -> bytes:
            chunk, self.remaining = self.remaining, b""
            return chunk

        def close(self) -> None:
            responses_closed.append(self.address)

    class FakeHTTPS:
        def __init__(self, host: str, address: public_download.Address) -> None:
            self.address = address

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            attempted.append(self.address)

        def getresponse(self) -> Response:
            return Response(self.address)

        def close(self) -> None:
            connections_closed.append(self.address)

    monkeypatch.setattr(public_download, "public_addresses", lambda _host: addresses)
    monkeypatch.setattr(public_download, "PinnedHTTPSConnection", FakeHTTPS)
    target = tmp_path / "download"
    with target.open("wb") as destination:
        receipt = public_download.fetch("https://huggingface.co/file", destination.fileno(), 100)
    assert attempted == responses_closed == connections_closed == addresses
    assert target.read_bytes() == body
    assert receipt == {"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}


def test_download_truncated_body_fails_over_without_partial_contamination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addresses: list[public_download.Address] = [
        (socket.AF_INET, ("8.8.8.8", 443)),
        (socket.AF_INET, ("8.8.4.4", 443)),
    ]
    attempted: list[public_download.Address] = []
    responses_closed: list[public_download.Address] = []
    connections_closed: list[public_download.Address] = []
    complete = b"exact complete body"

    class Response:
        status = 200

        def __init__(self, address: public_download.Address, body: bytes, declared: int) -> None:
            self.address = address
            self.remaining = body
            self.declared = declared

        def getheader(self, name: str) -> str | None:
            return str(self.declared) if name == "Content-Length" else None

        def read(self, _size: int) -> bytes:
            chunk, self.remaining = self.remaining, b""
            return chunk

        def close(self) -> None:
            responses_closed.append(self.address)

    class FakeHTTPS:
        def __init__(self, host: str, address: public_download.Address) -> None:
            self.address = address

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            attempted.append(self.address)

        def getresponse(self) -> Response:
            if self.address == addresses[0]:
                return Response(self.address, b"partial first body", 100)
            return Response(self.address, complete, len(complete))

        def close(self) -> None:
            connections_closed.append(self.address)

    monkeypatch.setattr(public_download, "public_addresses", lambda _host: addresses)
    monkeypatch.setattr(public_download, "PinnedHTTPSConnection", FakeHTTPS)
    target = tmp_path / "download"
    with target.open("wb") as destination:
        receipt = public_download.fetch("https://huggingface.co/file", destination.fileno(), 100)
    assert attempted == responses_closed == connections_closed == addresses
    assert target.read_bytes() == complete
    assert receipt == {
        "sha256": hashlib.sha256(complete).hexdigest(),
        "byte_length": len(complete),
    }


@pytest.mark.parametrize("failure", ["http", "body"])
def test_download_all_address_http_and_body_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    addresses: list[public_download.Address] = [
        (socket.AF_INET, (f"8.8.8.{index}", 443)) for index in range(1, 4)
    ]
    attempted: list[public_download.Address] = []
    responses_closed: list[public_download.Address] = []
    connections_closed: list[public_download.Address] = []

    class Response:
        def __init__(self, address: public_download.Address) -> None:
            self.address = address
            self.status = 503 if failure == "http" else 200
            self.reads = 0

        def getheader(self, name: str) -> str | None:
            return "10" if name == "Content-Length" and failure == "body" else None

        def read(self, _size: int) -> bytes:
            self.reads += 1
            if self.reads == 1:
                return b"partial"
            raise OSError("private body diagnostic")

        def close(self) -> None:
            responses_closed.append(self.address)

    class FailingHTTPS:
        def __init__(self, host: str, address: public_download.Address) -> None:
            self.address = address

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            attempted.append(self.address)

        def getresponse(self) -> Response:
            return Response(self.address)

        def close(self) -> None:
            connections_closed.append(self.address)

    monkeypatch.setattr(public_download, "public_addresses", lambda _host: addresses)
    monkeypatch.setattr(public_download, "PinnedHTTPSConnection", FailingHTTPS)
    with (
        (tmp_path / "stage").open("wb") as destination,
        pytest.raises(OSError, match="^public download attempt failed$"),
    ):
        public_download.fetch("https://huggingface.co/file", destination.fileno(), 100)
    assert attempted == responses_closed == connections_closed == addresses


def test_download_size_limit_does_not_fail_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addresses: list[public_download.Address] = [
        (socket.AF_INET, ("8.8.8.8", 443)),
        (socket.AF_INET, ("8.8.4.4", 443)),
    ]
    attempted: list[public_download.Address] = []
    responses_closed: list[public_download.Address] = []
    connections_closed: list[public_download.Address] = []

    class OversizedResponse:
        status = 200

        def __init__(self, address: public_download.Address) -> None:
            self.address = address

        def getheader(self, name: str) -> str | None:
            return "101" if name == "Content-Length" else None

        def close(self) -> None:
            responses_closed.append(self.address)

    class FakeHTTPS:
        def __init__(self, host: str, address: public_download.Address) -> None:
            self.address = address

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            attempted.append(self.address)

        def getresponse(self) -> OversizedResponse:
            return OversizedResponse(self.address)

        def close(self) -> None:
            connections_closed.append(self.address)

    monkeypatch.setattr(public_download, "public_addresses", lambda _host: addresses)
    monkeypatch.setattr(public_download, "PinnedHTTPSConnection", FakeHTTPS)
    with (
        (tmp_path / "stage").open("wb") as destination,
        pytest.raises(ValueError, match="artifact exceeds limit"),
    ):
        public_download.fetch("https://huggingface.co/file", destination.fileno(), 100)
    assert attempted == responses_closed == connections_closed == addresses[:1]


def test_download_all_address_failure_is_bounded_and_generic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addresses: list[public_download.Address] = [
        (socket.AF_INET, (f"8.8.8.{index}", 443)) for index in range(1, 4)
    ]
    attempted: list[public_download.Address] = []

    class FailingHTTPS:
        def __init__(self, host: str, address: public_download.Address) -> None:
            self.address = address

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            attempted.append(self.address)
            raise OSError("private per-address diagnostic")

        def close(self) -> None:
            pass

    monkeypatch.setattr(public_download, "public_addresses", lambda _host: addresses)
    monkeypatch.setattr(public_download, "PinnedHTTPSConnection", FailingHTTPS)
    with (
        (tmp_path / "stage").open("wb") as destination,
        pytest.raises(OSError, match="^public download attempt failed$"),
    ):
        public_download.fetch("https://huggingface.co/file", destination.fileno(), 100)
    assert attempted == addresses


def test_dns_address_inventory_is_deduplicated_sorted_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.4.4", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: answers)
    assert public_download.public_addresses("huggingface.co") == [
        (socket.AF_INET, ("8.8.4.4", 443)),
        (socket.AF_INET, ("8.8.8.8", 443)),
    ]
    answers[:] = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (f"8.8.8.{i}", 443))
        for i in range(1, public_download.MAX_PUBLIC_ADDRESSES + 2)
    ]
    with pytest.raises(ValueError, match="too many addresses"):
        public_download.public_addresses("huggingface.co")


@pytest.mark.parametrize("phase", ["dns", "headers", "body"])
def test_parent_wall_deadline_bounds_stalls_and_trickles_and_cleans_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    def stall(url: str, fd: int, max_bytes: int) -> dict[str, JSON]:
        if phase in {"dns", "headers"}:
            time.sleep(10)
        while True:
            os.write(fd, b"x")
            time.sleep(0.02)  # Never hits an inactivity timeout; total wall deadline must fire.

    monkeypatch.setattr(public_download, "fetch", stall)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="deadline"):
        download("https://huggingface.co/test", tmp_path / "result", 100, seconds=0.15)
    assert time.monotonic() - started < 2
    assert entries(tmp_path) == []


def test_public_artifact_ceiling_passes_and_ceiling_plus_one_fails_before_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[str] = []

    class BoundsPassed(Exception):
        pass

    def stop_before_process(method: str) -> None:
        contexts.append(method)
        raise BoundsPassed

    monkeypatch.setattr("multiprocessing.get_context", stop_before_process)
    with pytest.raises(BoundsPassed):
        public_download.bounded_fetch(
            "https://huggingface.co/test",
            -1,
            public_download.MAX_PUBLIC_ARTIFACT_BYTES,
            1,
        )
    with pytest.raises(ValueError, match="invalid acquisition bounds"):
        public_download.bounded_fetch(
            "https://huggingface.co/test",
            -1,
            public_download.MAX_PUBLIC_ARTIFACT_BYTES + 1,
            1,
        )
    assert contexts == ["fork"]


def test_download_checks_size_hash_and_no_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"synthetic public-download body"

    def fake(url: str, fd: int, max_bytes: int) -> dict[str, JSON]:
        os.write(fd, body)
        return {"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}

    monkeypatch.setattr(public_download, "fetch", fake)
    target = tmp_path / "artifact"
    receipt = download("https://huggingface.co/test", target, 100)
    assert receipt["byte_length"] == len(body)
    with pytest.raises(ValueError, match="unverified"):
        download("https://huggingface.co/test", target, 100)
    assert read_bytes(target) == body
    with pytest.raises(ValueError, match="digest"):
        download("https://huggingface.co/test", tmp_path / "mismatch", 100, expected="0" * 64)
    assert entries(tmp_path) == ["artifact"]


@pytest.mark.parametrize("mismatch", ["size", "md5"])
def test_download_rejects_wrong_expected_size_or_md5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    body = jpeg()

    def fake(url: str, fd: int, max_bytes: int) -> dict[str, JSON]:
        os.write(fd, body)
        return {"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}

    monkeypatch.setattr(public_download, "fetch", fake)
    expected_length = len(body) + (1 if mismatch == "size" else 0)
    expected_md5 = (
        "0" * 32 if mismatch == "md5" else hashlib.md5(body, usedforsecurity=False).hexdigest()
    )
    with pytest.raises(ValueError, match="length|MD5"):
        download(
            "https://huggingface.co/test",
            tmp_path / "image.jpg",
            1024 * 1024,
            expected_length=expected_length,
            expected_md5=expected_md5,
        )
    assert entries(tmp_path) == []


@pytest.mark.parametrize("directory_name", ["images", "metadata"])
def test_directory_symlink_cannot_write_outside_artifact_root(
    tmp_path: Path,
    directory_name: str,
) -> None:
    root, outside = tmp_path / "data", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"untouched")
    (root / directory_name).symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        prepare(root, 48)
    assert sentinel.read_bytes() == b"untouched"
    assert entries(outside) == ["sentinel"]


def test_fixed_partial_symlink_is_ignored_and_existing_json_not_overwritten(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"untouched")
    (tmp_path / "receipt.json.partial").symlink_to(sentinel)
    target = tmp_path / "receipt.json"
    write_json(target, {"valid": True})
    original = target.read_bytes()
    with pytest.raises(ValueError):
        write_json(target, {"valid": False})
    assert target.read_bytes() == original and sentinel.read_bytes() == b"untouched"
    assert (tmp_path / "receipt.json.partial").is_symlink()


def test_artifact_root_and_retained_files_reject_writable_modes(tmp_path: Path) -> None:
    retained = tmp_path / "retained"
    retained.write_bytes(b"trusted only when not writable by group or other")
    retained.chmod(0o662)
    with pytest.raises(ValueError, match="group or other writable"):
        read_bytes(retained)
    retained.chmod(0o600)
    tmp_path.chmod(0o777)
    try:
        with pytest.raises(ValueError, match="group or other writable"):
            entries(tmp_path)
    finally:
        tmp_path.chmod(0o700)


def test_artifact_owner_is_checked_from_open_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = tmp_path / "retained"
    retained.write_bytes(b"synthetic")
    monkeypatch.setattr(os, "geteuid", lambda: retained.stat().st_uid + 1)
    with pytest.raises(ValueError, match="effective user"):
        read_bytes(retained)


def test_root_owned_sticky_tmp_ancestry_is_accepted(tmp_path: Path) -> None:
    retained = tmp_path / "retained"
    retained.write_bytes(b"synthetic")
    assert read_bytes(retained) == b"synthetic"


def jpeg(color: str = "red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def completed_dataset(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    old_profile: bool = False,
    actual_count: int = 48,
    requested_count: int = 48,
) -> dict[str, JSON]:
    ensure_directory(root / "images")
    ensure_directory(root / "metadata")
    items: list[Item] = []
    for index in range(actual_count):
        identity = f"{index:016x}"
        path = root / "images" / f"{identity}.jpg"
        path.write_bytes(jpeg())
        items.append(Item(identity, "images/" + path.name, file_digest(path), path.stat().st_size))
    original_content = {
        item.id: (
            item.byte_length + 10_000,
            hashlib.md5(
                ("synthetic original source " + item.id).encode(), usedforsecurity=False
            ).hexdigest(),
        )
        for item in items
    }
    hashes: dict[str, str] = {}
    metadata: dict[str, JSON] = {}
    for name, suffix in METADATA.items():
        path = root / "metadata" / name
        path.write_bytes(b"synthetic-metadata:" + name.encode())
        hashes[name] = file_digest(path)
        metadata[name] = {"sha256": hashes[name], "source": BUCKET + suffix}
    monkeypatch.setattr("memotrace_ml.openimages.METADATA_SHA256", hashes)
    profile = CLASS_PROFILE[:5] if old_profile else CLASS_PROFILE
    selection: dict[str, JSON] = {
        "version": "openimages-tools-pilot-v1" if old_profile else SELECTION_VERSION,
        "actual_count": actual_count,
        "requested_count": requested_count,
        "missing_count": requested_count - actual_count,
        "selected_ids": [item.id for item in items],
        "selected_content": [
            {
                "id": item.id,
                "sha256": item.sha256,
                "byte_length": item.byte_length,
                "original_size": original_content[item.id][0],
                "original_md5": original_content[item.id][1],
            }
            for item in items
        ],
        "metadata": metadata,
        "classes": {name: {} for name, _ in profile},
    }
    if not old_profile:
        selection["class_profile"] = class_profile()
    write_json(root / "selection.json", selection)
    write_json(
        root / "ground-truth.json",
        {
            "version": "1",
            "classes": {mid: {"name": name} for name, mid in profile},
        },
    )
    write_json(
        root / "manifest.json",
        {
            "version": "1",
            "dataset": {
                "name": "openimages-tools-validation" if old_profile else DATASET_NAME,
                "version": ("v5-pilot1-" if old_profile else DATASET_VERSION_PREFIX)
                + fingerprint(selection)[:16],
                "source": SOURCE,
                "license": LICENSE,
            },
            "items": [item.json() for item in items],
        },
    )
    attribution: dict[str, JSON] = {
        item.id: {
            "download": {
                "source": IMAGE_BUCKET + item.id + ".jpg",
                "sha256": item.sha256,
                "byte_length": item.byte_length,
            },
            "license": LICENSE,
            "author": "Synthetic Author",
            "title": "Synthetic title " + item.id,
            "author_profile_url": "https://example.invalid/author",
            "original_url": "https://example.invalid/image/" + item.id,
            "landing_url": "https://example.invalid/landing/" + item.id,
            "rotation": "0",
            "original_size": original_content[item.id][0],
            "original_md5": original_content[item.id][1],
        }
        for item in items
    }
    write_json(root / "attribution.json", attribution)
    receipt: dict[str, JSON] = {
        "count": actual_count,
        "manifest_sha256": file_digest(root / "manifest.json"),
        "ground_truth_sha256": file_digest(root / "ground-truth.json"),
        "selection_sha256": file_digest(root / "selection.json"),
        "attribution_sha256": file_digest(root / "attribution.json"),
    }
    write_json(root / "acquisition.json", receipt)
    return receipt


def profile_documents() -> tuple[dict[str, JSON], dict[str, JSON], dict[str, JSON]]:
    selection: dict[str, JSON] = {
        "version": SELECTION_VERSION,
        "class_profile": class_profile(),
        "classes": {name: {} for name, _ in CLASS_PROFILE},
    }
    ground_truth: dict[str, JSON] = {
        "version": "1",
        "classes": {mid: {"name": name} for name, mid in CLASS_PROFILE},
    }
    dataset: dict[str, JSON] = {
        "name": DATASET_NAME,
        "version": DATASET_VERSION_PREFIX + fingerprint(selection)[:16],
        "source": SOURCE,
        "license": LICENSE,
    }
    return selection, ground_truth, dataset


def test_ordered_everyday_object_profile_identity_and_round_robin() -> None:
    assert CLASS_PROFILE == (
        ("Screwdriver", "/m/01bms0"),
        ("Scissors", "/m/01lsmm"),
        ("Hammer", "/m/03l9g"),
        ("Knife", "/m/04ctx"),
        ("Pen", "/m/0k1tl"),
        ("Bottle", "/m/04dr76w"),
        ("Mug", "/m/02jvh9"),
        ("Mobile phone", "/m/050k8"),
    )
    assert class_profile() == {
        "id": CLASS_PROFILE_ID,
        "version": CLASS_PROFILE_VERSION,
        "classes": [{"name": name, "mid": mid} for name, mid in CLASS_PROFILE],
    }
    labels: dict[str, dict[str, bool]] = {mid: {} for mid in CLASSES.values()}
    labels[CLASSES["Screwdriver"]] = {"a": True, "b": False, "z": True}
    labels[CLASSES["Scissors"]] = {"a": True, "c": False, "y": True}
    assert round_robin_candidates(labels, {"a", "b", "c", "y", "z"}) == [
        "a",
        "b",
        "c",
        "z",
        "y",
    ]


@pytest.mark.parametrize(
    "mismatch",
    [
        "selection_version",
        "profile_id",
        "profile_version",
        "profile_order",
        "selection_names",
        "ground_mid",
        "ground_name",
        "dataset_name",
        "dataset_version",
    ],
)
def test_profile_validation_rejects_mismatched_identity(mismatch: str) -> None:
    selection, ground_truth, dataset = profile_documents()
    if mismatch == "selection_version":
        selection["version"] = "old"
    elif mismatch in {"profile_id", "profile_version"}:
        profile = object_value(selection["class_profile"])
        profile[mismatch.removeprefix("profile_")] = "old"
    elif mismatch == "profile_order":
        selection["class_profile"] = {
            "id": CLASS_PROFILE_ID,
            "version": CLASS_PROFILE_VERSION,
            "classes": [{"name": name, "mid": mid} for name, mid in reversed(CLASS_PROFILE)],
        }
    elif mismatch == "selection_names":
        selection["classes"] = {"Wrong": {}}
    elif mismatch == "ground_mid":
        object_value(ground_truth["classes"]).pop(CLASS_PROFILE[0][1])
    elif mismatch == "ground_name":
        object_value(object_value(ground_truth["classes"])[CLASS_PROFILE[0][1]])["name"] = "Wrong"
    elif mismatch == "dataset_name":
        dataset["name"] = "old"
    else:
        dataset["version"] = "old"
    with pytest.raises(ValueError, match="profile mismatch"):
        validate_acquisition_profile(selection, ground_truth, dataset)


def test_old_five_class_root_rejected_before_image_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "old-data"
    completed_dataset(root, monkeypatch, old_profile=True)

    def unexpected_image_verification(path: Path) -> tuple[dict[str, JSON], list[Item]]:
        raise AssertionError(f"old profile reached image reuse: {path}")

    monkeypatch.setattr("memotrace_ml.openimages.load_items", unexpected_image_verification)
    with pytest.raises(ValueError):
        verified_acquisition(root)


def test_completed_receipted_dataset_resumes_without_rewriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    receipt = completed_dataset(root, monkeypatch)
    before = {name: (root / name).read_bytes() for name in entries(root) if name.endswith(".json")}
    assert prepare(root, 48) == receipt
    assert {name: (root / name).read_bytes() for name in before} == before


def test_incomplete_receipted_dataset_cannot_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    completed_dataset(root, monkeypatch, actual_count=47, requested_count=48)
    with pytest.raises(ValueError, match="incomplete or inconsistent acquisition"):
        prepare(root, 48)


@pytest.mark.parametrize("mismatch", ["missing", "receipt", "entry", "title", "download"])
def test_current_profile_requires_exact_complete_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    root = tmp_path / "data"
    completed_dataset(root, monkeypatch)
    attribution_path = root / "attribution.json"
    receipt_path = root / "acquisition.json"
    if mismatch == "missing":
        attribution_path.unlink()
    elif mismatch == "receipt":
        receipt = read_json(receipt_path)
        receipt["attribution_sha256"] = "0" * 64
        receipt_path.unlink()
        write_json(receipt_path, receipt)
    else:
        attribution = read_json(attribution_path)
        if mismatch == "entry":
            attribution.pop("0000000000000000")
        elif mismatch == "download":
            entry = object_value(attribution["0000000000000000"])
            object_value(entry["download"])["byte_length"] = 1
        else:
            object_value(attribution["0000000000000000"])["title"] = ""
        attribution_path.unlink()
        write_json(attribution_path, attribution)
        receipt = read_json(receipt_path)
        receipt["attribution_sha256"] = file_digest(attribution_path)
        receipt_path.unlink()
        write_json(receipt_path, receipt)
    with pytest.raises((FileNotFoundError, ValueError)):
        verified_acquisition(root)


def test_attribution_distinguishes_original_metadata_from_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    completed_dataset(root, monkeypatch)
    _, items = load_items(root / "manifest.json")
    attribution = read_json(root / "attribution.json")
    validate_attribution(attribution, items)
    entry = object_value(attribution[items[0].id])
    actual = object_value(entry["download"])
    assert entry["title"] == "Synthetic title " + items[0].id
    assert entry["original_size"] != actual["byte_length"]
    assert (
        entry["original_md5"]
        != hashlib.md5((root / items[0].path).read_bytes(), usedforsecurity=False).hexdigest()
    )


def test_incomplete_cli_receipt_exits_nonzero_and_retains_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt: dict[str, JSON] = {"count": 0}

    def incomplete(root: Path, count: int) -> dict[str, JSON]:
        assert root == tmp_path and count == 48
        write_json(root / "acquisition.json", receipt)
        return receipt

    monkeypatch.setattr("memotrace_ml.openimages.prepare", incomplete)
    with pytest.raises(SystemExit, match="requested subset incomplete") as raised:
        openimages.main(["--data-dir", str(tmp_path), "--count", "48"])
    assert raised.value.code != 0
    assert read_json(tmp_path / "acquisition.json") == receipt


def test_cli_rejects_unverified_complete_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("memotrace_ml.openimages.prepare", lambda root, count: {"count": count})

    def reject(root: Path) -> tuple[dict[str, JSON], dict[str, JSON], list[Item]]:
        raise ValueError("synthetic verification failure")

    monkeypatch.setattr("memotrace_ml.openimages.verified_acquisition", reject)
    with pytest.raises(ValueError, match="synthetic verification failure"):
        openimages.main(["--data-dir", str(tmp_path), "--count", "48"])


def test_dataset_version_identity_changes_when_selected_bytes_change() -> None:
    selection, _, _ = profile_documents()
    selection["selected_ids"] = ["image"]
    selected_content: list[JSON] = [
        {
            "id": "image",
            "sha256": "a" * 64,
            "byte_length": 10,
            "original_size": 10,
            "original_md5": "b" * 32,
        }
    ]
    selection["selected_content"] = selected_content
    first = DATASET_VERSION_PREFIX + fingerprint(selection)[:16]
    object_value(selected_content[0])["sha256"] = "c" * 64
    second = DATASET_VERSION_PREFIX + fingerprint(selection)[:16]
    assert first != second


def test_valid_jpeg_substitution_fails_before_any_metadata_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    completed_dataset(root, monkeypatch)
    before = {name: (root / name).read_bytes() for name in entries(root) if name.endswith(".json")}
    (root / "images" / "0000000000000000.jpg").write_bytes(jpeg("blue"))
    with pytest.raises(ValueError, match="integrity"):
        prepare(root, 48)
    assert {name: (root / name).read_bytes() for name in before} == before


def test_unreceipted_valid_jpeg_never_gets_official_provenance(tmp_path: Path) -> None:
    ensure_directory(tmp_path / "images")
    existing = tmp_path / "images" / "0000000000000000.jpg"
    existing.write_bytes(jpeg())
    with pytest.raises(ValueError, match="unverified"):
        prepare(tmp_path, 48)
    assert existing.read_bytes() == jpeg()
    assert entries(tmp_path) == ["images"]


@pytest.mark.parametrize("rejection", ["invalid-body", "exif-rotation"])
def test_large_originals_with_small_valid_cvdf_images_publish_a_resumable_subset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rejection: str,
) -> None:
    def csv_bytes(rows: list[list[str]]) -> bytes:
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerows(rows)
        return buffer.getvalue().encode()

    identities = [f"{index:016x}" for index in range(49)]
    mid = CLASSES["Screwdriver"]
    valid = jpeg()
    if rejection == "invalid-body":
        rejected = b"invalid HTTP image body"
    else:
        buffer = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (12, 8), "red").save(buffer, format="JPEG", exif=exif)
        rejected = buffer.getvalue()
    image_bodies = {identity: valid for identity in identities}
    image_bodies[identities[0]] = rejected
    original_sizes = {
        identity: MAX_IMAGE_BYTES + index + 1 for index, identity in enumerate(identities)
    }
    original_md5s = {
        identity: hashlib.md5(
            ("synthetic original source " + identity).encode(), usedforsecurity=False
        ).digest()
        for identity in identities
    }
    metadata = {
        "classes.csv": csv_bytes([[value, name] for name, value in CLASSES.items()]),
        "labels.csv": csv_bytes(
            [
                ["ImageID", "Source", "LabelName", "Confidence"],
                *[[identity, "verification", mid, "1"] for identity in identities],
            ]
        ),
        "boxes.csv": csv_bytes(
            [
                [
                    "ImageID",
                    "LabelName",
                    "XMin",
                    "YMin",
                    "XMax",
                    "YMax",
                    "IsOccluded",
                    "IsTruncated",
                    "IsGroupOf",
                    "IsDepiction",
                ],
                *[
                    [identity, mid, "0", "0", "1", "1", "0", "0", "0", "0"]
                    for identity in identities
                ],
            ]
        ),
        "images.csv": csv_bytes(
            [
                [
                    "ImageID",
                    "License",
                    "Rotation",
                    "Author",
                    "Title",
                    "AuthorProfileURL",
                    "OriginalURL",
                    "OriginalLandingURL",
                    "OriginalSize",
                    "OriginalMD5",
                ],
                *[
                    [
                        identity,
                        LICENSE,
                        "0",
                        "synthetic",
                        "Synthetic supplied title " + identity,
                        "https://example.invalid/author",
                        "https://example.invalid/image",
                        "https://example.invalid/landing",
                        str(original_sizes[identity]),
                        base64.b64encode(original_md5s[identity]).decode("ascii"),
                    ]
                    for identity in identities
                ],
            ]
        ),
    }
    bodies = {BUCKET + METADATA[name]: body for name, body in metadata.items()}
    bodies.update(
        {IMAGE_BUCKET + identity + ".jpg": image_bodies[identity] for identity in identities}
    )
    monkeypatch.setattr(
        "memotrace_ml.openimages.METADATA_SHA256",
        {name: hashlib.sha256(body).hexdigest() for name, body in metadata.items()},
    )

    def fake_fetch(url: str, fd: int, max_bytes: int) -> dict[str, JSON]:
        body = bodies[url]
        assert len(body) <= max_bytes
        os.write(fd, body)
        return {"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}

    # Exercise the real downloader's staging/validation/publication and parent deadline;
    # only the network fetch is synthetic. Never publish or clean an unknown file.
    monkeypatch.setattr(public_download, "fetch", fake_fetch)
    receipt = prepare(tmp_path, 48)
    assert receipt["count"] == 48
    assert set(entries(tmp_path / "images")) == {identity + ".jpg" for identity in identities[1:]}
    selection = read_json(tmp_path / "selection.json")
    assert selection["version"] == SELECTION_VERSION
    assert selection["class_profile"] == class_profile()
    assert set(object_value(selection["classes"])) == {name for name, _ in CLASS_PROFILE}
    assert "size" not in object_value(selection["rejected_metadata"])
    ground_truth = object_value(read_json(tmp_path / "ground-truth.json")["classes"])
    assert set(ground_truth) == {mid for _, mid in CLASS_PROFILE}
    assert all(object_value(ground_truth[mid])["name"] == name for name, mid in CLASS_PROFILE)
    assert selection["download_failures"] == [
        {
            "id": identities[0],
            "reason": "download_decode_or_orientation_failed",
        }
    ]
    first_selected = identities[1]
    first_content = object_value(list_value(selection["selected_content"])[0])
    first_attribution = object_value(read_json(tmp_path / "attribution.json")[first_selected])
    first_download = object_value(first_attribution["download"])
    assert first_content == {
        "id": first_selected,
        "sha256": hashlib.sha256(valid).hexdigest(),
        "byte_length": len(valid),
        "original_size": original_sizes[first_selected],
        "original_md5": original_md5s[first_selected].hex(),
    }
    assert first_download["byte_length"] == len(valid)
    assert original_sizes[first_selected] > MAX_IMAGE_BYTES > len(valid)
    assert first_attribution["original_size"] == original_sizes[first_selected]
    assert (
        first_attribution["original_md5"] != hashlib.md5(valid, usedforsecurity=False).hexdigest()
    )
    assert verified_acquisition(tmp_path)[0] == receipt
    assert prepare(tmp_path, 48) == receipt
    openimages.main(["--data-dir", str(tmp_path), "--count", "48"])
    unknown = tmp_path / "images" / "unrecognized.jpg"
    unknown.write_bytes(b"preexisting unknown sentinel")
    with pytest.raises(ValueError, match="unverified image"):
        verified_acquisition(tmp_path)
    assert unknown.read_bytes() == b"preexisting unknown sentinel"
