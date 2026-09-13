"""Explicit live-weight JSONL smoke with synthetic JPEGs, not a quality evaluation."""

import argparse
import base64
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

from memotrace_ml.common import JSON, canonical, list_value, object_value, parse_json


def smoke_environment(home: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "UV_OFFLINE": "1",
        "UV_NO_SYNC": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "TOKENIZERS_PARALLELISM": "false",
    }


def process_group_alive(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_owned(
    process: subprocess.Popen[bytes], graceful_seconds: float, kill_seconds: float
) -> tuple[bytes, bytes]:
    if process_group_alive(process.pid):
        os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + graceful_seconds
    while process_group_alive(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.01)
    forced = process_group_alive(process.pid)
    if forced:
        os.killpg(process.pid, signal.SIGKILL)
    try:
        stdout, stderr = process.communicate(timeout=kill_seconds)
    except subprocess.TimeoutExpired:
        raise RuntimeError("owned worker cleanup failed") from None
    if forced:
        raise RuntimeError("owned worker required forced termination")
    return stdout, stderr


def run_owned_worker(
    argv: list[str],
    body: bytes,
    environment: dict[str, str],
    timeout: float = 180,
    graceful_seconds: float = 10,
    kill_seconds: float = 5,
) -> tuple[bytes, bytes]:
    try:
        process: subprocess.Popen[bytes] = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
    except OSError:
        raise RuntimeError("live worker failed to start") from None
    try:
        stdout, stderr = process.communicate(body, timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_owned(process, graceful_seconds, kill_seconds)
        raise RuntimeError("live worker timed out after graceful termination") from None
    if process_group_alive(process.pid):
        terminate_owned(process, graceful_seconds, kill_seconds)
        raise RuntimeError("live worker left an owned descendant")
    if process.returncode != 0:
        raise RuntimeError("live worker exited unsuccessfully")
    return stdout, stderr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (160, 90), "red").save(buffer, format="JPEG", exif=exif)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    requests: list[JSON] = [
        {"id": "describe", "op": "describe"},
        {"id": "en", "op": "text", "text": "a photo of a screwdriver"},
        {"id": "ru", "op": "text", "text": "фотография отвёртки"},
        {"id": "full", "op": "image", "mode": "full", "image_base64": encoded},
        {"id": "overlap", "op": "image", "mode": "overlap", "image_base64": encoded},
        {"id": "query", "op": "query_image", "box": [0, 0, 0.5, 0.5], "image_base64": encoded},
        {"id": "long", "op": "text", "text": "word " * 100},
        {"id": "recovered", "op": "describe"},
    ]
    for identity, box in (
        ("tiny", "[0,0,1e-400,1]"),
        ("close", "[0.5,0,0.50000000000000001,1]"),
        ("extreme", "[0,0,1e-9999999999999999999999999999,1]"),
    ):
        requests.append(
            parse_json(
                b'{"id":'
                + canonical(identity)
                + b',"op":"query_image","image_base64":'
                + canonical(encoded)
                + b',"box":'
                + box.encode()
                + b"}",
                exact_numbers=True,
            )
        )
    requests.append(
        {
            "id": "bad-image",
            "op": "query_image",
            "image_base64": base64.b64encode(b"invalid JPEG").decode(),
        }
    )
    requests.append({"id": "decode-recovered", "op": "describe"})
    small = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(small, format="JPEG")
    long_significand = (
        b'{"id":"long-significand","op":"query_image","image_base64":'
        + canonical(base64.b64encode(small.getvalue()).decode())
        + b',"box":[0.5,0,0.5'
        + b"0" * 1_000_000
        + b"1,1]}"
    )
    if len(long_significand) >= 1024 * 1024:
        raise ValueError("long-significand fixture exceeds public request bound")
    requests.append(parse_json(long_significand, exact_numbers=True))
    with tempfile.TemporaryDirectory(prefix="memotrace-ml-smoke-") as temporary_home:
        stdout, stderr = run_owned_worker(
            [sys.executable, "-m", "memotrace_ml.worker", "--model-dir", str(args.model_dir)],
            b"\n".join(canonical(request) for request in requests) + b"\n",
            smoke_environment(Path(temporary_home)),
        )
    if stderr:
        raise RuntimeError("live worker emitted private stderr diagnostics")
    responses = [object_value(parse_json(line)) for line in stdout.splitlines()]
    if len(responses) != len(requests):
        raise ValueError("unexpected response count")
    for response, request in zip(responses, requests, strict=True):
        request_id = object_value(request)["id"]
        if response["id"] != request_id or response["ok"] != (
            request_id not in {"long", "bad-image"}
        ):
            raise ValueError("unexpected live response")
        if request_id == "bad-image" and response.get("error") != "input_failed":
            raise ValueError("original-image failure mapping mismatch")
    by_id = {response["id"]: response for response in responses}
    if by_id["decode-recovered"].get("ok") is not True:
        raise ValueError("worker did not recover after original-image failure")
    if by_id["decode-recovered"].get("model_fingerprint") != responses[0].get("model_fingerprint"):
        raise ValueError("worker identity changed after original-image failure")
    if responses[6].get("error") != "invalid_request" or responses[7].get("ok") is not True:
        raise ValueError("over-tokenized text recovery mismatch")
    if responses[7].get("model_fingerprint") != responses[0].get("model_fingerprint"):
        raise ValueError("worker identity changed after invalid text")
    for response in responses[3:5]:
        if response["width"] != 90 or response["height"] != 160:
            raise ValueError("EXIF coordinate mismatch")
    if len(list_value(responses[3]["vectors"])) != 1:
        raise ValueError("full region mismatch")
    if len(list_value(responses[4]["vectors"])) != 7:
        raise ValueError("overlap region mismatch")
    print(
        canonical(
            {
                "status": "passed",
                "requests": len(requests),
                "model": responses[0],
                "stderr_bytes": len(stderr),
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
