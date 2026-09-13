"""HTTPS-only allowlisted acquisition with pinned public DNS addresses and a deadline."""

import hashlib
import http.client
import ipaddress
import multiprocessing
import os
import socket
import ssl
import time
from multiprocessing.connection import Connection
from urllib.parse import SplitResult, urljoin, urlsplit

from memotrace_ml.common import JSON, object_value

# Exact providers used by the pinned Hugging Face files, Google metadata and CVDF.
# No proxies, netrc, cookies, authorization headers, arbitrary hosts or IP literals.
ALLOWED_HOSTS = frozenset(
    {
        "huggingface.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs.hf.co",
        "cdn-lfs-us-1.hf.co",
        "cas-bridge.xethub.hf.co",
        "us.aws.cdn.hf.co",
        "storage.googleapis.com",
        "open-images-dataset.s3.amazonaws.com",
    }
)
MAX_PUBLIC_ARTIFACT_BYTES = 4_544_267_488
MAX_PUBLIC_ADDRESSES = 16
type Address = tuple[int, tuple[str, int] | tuple[str, int, int, int]]


def public_url(url: str) -> SplitResult:
    if len(url) > 16384 or any(ord(char) <= 32 or ord(char) >= 127 for char in url):
        raise ValueError("invalid download URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
        or "\\" in url
    ):
        raise ValueError("download provider is not allowed")
    return parsed


def public_addresses(host: str) -> list[Address]:
    results: set[Address] = set()
    for family, _, _, _, address in socket.getaddrinfo(
        host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    ):
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("download DNS contains a non-public address")
        if family == socket.AF_INET:
            results.add((family, (str(ip), 443)))
        elif family == socket.AF_INET6:
            results.add((family, (str(ip), 443, 0, 0)))
        else:
            raise ValueError("invalid address family")
    if not results:
        raise ValueError("download DNS has no addresses")
    if len(results) > MAX_PUBLIC_ADDRESSES:
        raise ValueError("download DNS has too many addresses")
    return sorted(results, key=lambda item: (item[0], ipaddress.ip_address(item[1][0]).packed))


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: Address) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(host, port=443, timeout=15, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        # Connect to the already validated numeric address, never resolve a second
        # time. TLS still verifies the original hostname and sends its SNI name.
        family, address = self.address
        raw = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            raw.settimeout(15)
            raw.connect(address)
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def fetch(url: str, fd: int, max_bytes: int) -> dict[str, JSON]:
    for _ in range(6):
        parsed = public_url(url)  # Before DNS or connecting, also for every redirect.
        assert parsed.hostname is not None
        addresses = public_addresses(parsed.hostname)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        redirected: str | None = None
        for address in addresses:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            connection: PinnedHTTPSConnection | None = None
            response: http.client.HTTPResponse | None = None
            try:
                connection = PinnedHTTPSConnection(parsed.hostname, address)
                connection.request("GET", path, headers={"User-Agent": "MemoTrace-public-pilot/2"})
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if location is None:
                        raise http.client.HTTPException("redirect without location")
                    redirected = urljoin(url, location)
                    public_url(redirected)  # Reject forbidden locations before following them.
                    break
                if response.status != 200:
                    raise OSError("public download HTTP failure")
                length_text = response.getheader("Content-Length")
                try:
                    length = int(length_text) if length_text is not None else None
                except (TypeError, ValueError):
                    raise http.client.HTTPException("invalid Content-Length") from None
                if length is not None and not 0 <= length <= max_bytes:
                    raise ValueError("artifact exceeds limit")
                digest = hashlib.sha256()
                size = 0
                with os.fdopen(os.dup(fd), "wb") as out:
                    while chunk := response.read(65536):
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("artifact exceeds limit")
                        out.write(chunk)
                        digest.update(chunk)
                if length is not None and size != length:
                    raise OSError("incomplete download")
                return {"sha256": digest.hexdigest(), "byte_length": size}
            except (OSError, http.client.HTTPException):
                continue
            finally:
                try:
                    if response is not None:
                        response.close()
                finally:
                    if connection is not None:
                        connection.close()
        if redirected is None:
            raise OSError("public download attempt failed")
        url = redirected
    raise ValueError("too many redirects")


def child_fetch(url: str, fd: int, max_bytes: int, result: Connection) -> None:
    try:
        for attempt in range(2):
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                os.ftruncate(fd, 0)
                receipt = fetch(url, fd, max_bytes)
                result.send(receipt)
                return
            except OSError:
                if attempt == 1:
                    raise
                time.sleep(0.25)
    except Exception:
        result.send({"error": "public download failed"})
    finally:
        result.close()


def bounded_fetch(url: str, fd: int, max_bytes: int, seconds: float) -> dict[str, JSON]:
    """Parent-owned wall deadline covers child DNS, TLS, headers, retries and body.

    Linux fork is intentional: one explicit downloader at a time, before any ML
    threads. A stalled child is terminated then killed with bounded cleanup.
    """
    if not 0 < seconds <= 1800 or not 0 < max_bytes <= MAX_PUBLIC_ARTIFACT_BYTES:
        raise ValueError("invalid acquisition bounds")
    public_url(url)
    context = multiprocessing.get_context("fork")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=child_fetch, args=(url, fd, max_bytes, send))
    started = time.monotonic()
    try:
        process.start()
        send.close()
        process.join(max(0, seconds - (time.monotonic() - started)))
        if process.is_alive():
            raise TimeoutError("public download wall deadline exceeded")
        if process.exitcode != 0 or not receive.poll():
            raise OSError("public download failed")
        receipt = object_value(receive.recv())
        if "error" in receipt:
            raise OSError("public download failed")
        return receipt
    finally:
        if process.is_alive():
            process.terminate()
            process.join(0.25)
        if process.is_alive():
            process.kill()
            process.join(0.25)
        receive.close()
        send.close()
        if not process.is_alive():
            process.close()
