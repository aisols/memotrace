#!/usr/bin/env python3
"""Run the genuine-model Go/PG/CLI/TLS smoke with optional private queries.

SPDX-License-Identifier: AGPL-3.0-only
Uses its own disposable PostgreSQL-15 container; never an operator DSN/database.
Model and manifest must already exist. Downloads no model or dataset artifacts.
Fixed evidence queries always run. Query IDs are non-sensitive artifact labels;
private query text is omitted from diagnostics and the summary. Optional sequence
IDs are also non-sensitive artifact labels for genuine history evidence.
"""

import argparse
import decimal
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

QUERY_ID = re.compile(r"(?:[a-z0-9]|[a-z0-9][a-z0-9-]{0,62}[a-z0-9])\Z")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_SAFE_INTEGER = 9007199254740991
MAX_FLOAT_DECIMAL = decimal.Decimal.from_float(sys.float_info.max)
HIT_FIELDS = {
    "asset_id",
    "source_kind",
    "frame_id",
    "dataset",
    "sha256",
    "score",
    "region",
    "observed_at_ms",
    "sequence_id",
    "sequence_position_ms",
    "original_path",
}


def smoke_environment(home):
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
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


def proxy_free_https_opener(tls_context):
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=tls_context),
    )


def process_group_alive(process_group):
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def signal_process_group(process_group, requested_signal):
    try:
        os.killpg(process_group, requested_signal)
    except ProcessLookupError:
        pass


def terminate_owned(process, graceful_seconds=10, kill_seconds=10, expected_status=None):
    signaled = process_group_alive(process.pid)
    if signaled:
        signal_process_group(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + graceful_seconds
    while process_group_alive(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.01)
    forced = process_group_alive(process.pid)
    if forced:
        signal_process_group(process.pid, signal.SIGKILL)
    try:
        stdout, stderr = process.communicate(timeout=kill_seconds)
    except subprocess.TimeoutExpired:
        raise RuntimeError("owned subprocess cleanup failed") from None
    if forced:
        raise RuntimeError("owned subprocess required forced termination")
    if expected_status is not None and process.returncode != expected_status:
        raise RuntimeError("owned subprocess had unexpected graceful status")
    return stdout, stderr, signaled


def run_owned(
    argv,
    *,
    cwd,
    env,
    body=None,
    timeout=900,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    graceful_seconds=10,
    kill_seconds=10,
):
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if body is not None else None,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    except OSError:
        raise RuntimeError("smoke subprocess failed (diagnostics intentionally private)") from None
    try:
        captured_stdout, captured_stderr = process.communicate(body, timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_owned(process, graceful_seconds, kill_seconds)
        raise RuntimeError("smoke subprocess timed out after graceful termination") from None
    if process_group_alive(process.pid):
        terminate_owned(process, graceful_seconds, kill_seconds)
        raise RuntimeError("smoke subprocess left an owned descendant")
    return subprocess.CompletedProcess(argv, process.returncode, captured_stdout, captured_stderr)


def parse_json_object(raw):
    def reject_duplicate_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value

    def reject_nonfinite(_value):
        raise ValueError("nonfinite JSON number")

    def parse_exact_decimal(value):
        try:
            number = decimal.Decimal(value)
        except decimal.DecimalException:
            raise ValueError("nonfinite JSON number") from None
        if not number.is_finite() or number.copy_abs() > MAX_FLOAT_DECIMAL:
            raise ValueError("nonfinite or overflowing JSON number")
        return number

    try:
        text = raw.decode("utf-8")
        document = json.loads(
            text,
            object_pairs_hook=reject_duplicate_fields,
            parse_constant=reject_nonfinite,
            parse_float=parse_exact_decimal,
        )
    except (AttributeError, UnicodeError, ValueError, RecursionError):
        raise ValueError(
            "response must be strict UTF-8 JSON without duplicate fields or nonfinite numbers"
        ) from None
    if type(document) is not dict:
        raise ValueError("response JSON must be a top-level object")
    return document


def exact_field(document, name, expected_type):
    if name not in document or type(document[name]) is not expected_type:
        raise RuntimeError("machine JSON response has invalid structure")
    return document[name]


def exact_score(document, name):
    value = document.get(name)
    if (
        type(value) not in (int, decimal.Decimal)
        or value < -1
        or value > 1
        or type(value) is decimal.Decimal
        and not value.is_finite()
    ):
        raise RuntimeError("machine JSON response has invalid structure")
    return value


def exact_coordinate(value):
    if type(value) not in (int, decimal.Decimal) or value < 0 or value > 1:
        raise RuntimeError("machine JSON response has invalid structure")
    return value


def exact_label(document, name, maximum):
    value = exact_field(document, name, str)
    if (
        not 1 <= len(value) <= maximum
        or "\0" in value
        or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
        raise RuntimeError("machine JSON response has invalid structure")
    return value


def validate_coverage(document, truncated):
    coverage = exact_field(document, "coverage", dict)
    if set(coverage) != {
        "assets_total",
        "assets_indexed",
        "pending",
        "failed",
        "regions_indexed",
    }:
        raise RuntimeError("machine JSON response has invalid structure")
    values = [exact_field(coverage, name, int) for name in coverage]
    if any(value < 0 or value > MAX_SAFE_INTEGER for value in values):
        raise RuntimeError("machine JSON response has invalid structure")
    if (
        coverage["assets_total"]
        != coverage["assets_indexed"] + coverage["pending"] + coverage["failed"]
        or coverage["regions_indexed"] < coverage["assets_indexed"]
        or coverage["assets_indexed"] == 0
        and coverage["regions_indexed"] != 0
    ):
        raise RuntimeError("machine JSON response has invalid structure")
    if coverage["assets_indexed"] == 0:
        raise RuntimeError("successful retrieval response has no indexed assets")
    if (coverage["pending"] or coverage["failed"]) and not truncated:
        raise RuntimeError("machine JSON response has invalid structure")
    return coverage


def validate_source_context(request, source_asset_id, source_sha256):
    query = exact_field(request, "query", dict)
    query_asset_id = query.get("asset_id")
    if query_asset_id is None:
        if source_asset_id is not None or source_sha256 is not None:
            raise RuntimeError("machine JSON response has invalid structure")
        return
    if (
        type(query_asset_id) is not str
        or UUID.fullmatch(query_asset_id) is None
        or source_asset_id != query_asset_id
        or type(source_sha256) is not str
        or SHA256.fullmatch(source_sha256) is None
    ):
        raise RuntimeError("machine JSON response has invalid structure")


def generated_json_bytes(value):
    def validate(item):
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise RuntimeError("generated summary is not JSON-compatible")
            for child in item.values():
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        elif type(item) is float:
            if not math.isfinite(item):
                raise RuntimeError("generated summary is not JSON-compatible")
        elif item is not None and type(item) not in (bool, int, str):
            raise RuntimeError("generated summary is not JSON-compatible")

    validate(value)
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_private_bytes(path, raw):
    if type(raw) is not bytes:
        raise RuntimeError("private artifact bytes required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        output = os.fdopen(descriptor, "wb")
        descriptor = None
        with output:
            output.write(raw)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def validate_hit_context(hit, archive_id, source_asset_id, source_sha256, threshold):
    if type(hit) is not dict or set(hit) != HIT_FIELDS:
        raise RuntimeError("machine JSON response has invalid structure")
    asset_id = exact_field(hit, "asset_id", str)
    sha256 = exact_field(hit, "sha256", str)
    score = exact_score(hit, "score")
    source_kind = exact_field(hit, "source_kind", str)
    frame_id = hit["frame_id"]
    dataset = hit["dataset"]
    if UUID.fullmatch(asset_id) is None:
        raise RuntimeError("machine JSON response has invalid structure")
    if source_kind == "frame":
        if type(frame_id) is not str or UUID.fullmatch(frame_id) is None or dataset is not None:
            raise RuntimeError("machine JSON response has invalid structure")
    elif source_kind == "dataset":
        if (
            frame_id is not None
            or type(dataset) is not dict
            or set(dataset)
            != {
                "name",
                "version",
                "item_id",
            }
        ):
            raise RuntimeError("machine JSON response has invalid structure")
        for name in dataset:
            exact_label(dataset, name, 512)
    else:
        raise RuntimeError("machine JSON response has invalid structure")
    if SHA256.fullmatch(sha256) is None:
        raise RuntimeError("machine JSON response has invalid structure")
    region = exact_field(hit, "region", dict)
    if set(region) != {"kind", "box"} or exact_field(region, "kind", str) not in {
        "full",
        "crop",
    }:
        raise RuntimeError("machine JSON response has invalid structure")
    box = exact_field(region, "box", list)
    if len(box) != 4:
        raise RuntimeError("machine JSON response has invalid structure")
    x0, y0, x1, y1 = (exact_coordinate(value) for value in box)
    if x0 >= x1 or y0 >= y1 or region["kind"] == "full" and box != [0, 0, 1, 1]:
        raise RuntimeError("machine JSON response has invalid structure")
    observed_at_ms = hit["observed_at_ms"]
    if observed_at_ms is not None:
        exact_milliseconds(hit, "observed_at_ms")
    sequence_id = hit["sequence_id"]
    sequence_position_ms = hit["sequence_position_ms"]
    if sequence_id is not None:
        exact_label(hit, "sequence_id", 256)
    if sequence_position_ms is not None:
        exact_milliseconds(hit, "sequence_position_ms")
    if (sequence_id is None) != (sequence_position_ms is None):
        raise RuntimeError("machine JSON response has invalid structure")
    expected_path = f"/v1/archives/{archive_id}/search/assets/{asset_id}/original"
    if exact_field(hit, "original_path", str) != expected_path:
        raise RuntimeError("machine JSON response has invalid structure")
    if (source_asset_id is not None and asset_id == source_asset_id) or (
        source_sha256 is not None and sha256 == source_sha256
    ):
        raise RuntimeError("image query self leak")
    if score < threshold:
        raise RuntimeError("retrieval response violates request threshold")
    return asset_id, score


def validate_search_response(
    document, request, expected_archive_id, source_asset_id, source_sha256
):
    if set(document) != {
        "contract_version",
        "archive_id",
        "generation_id",
        "coverage",
        "hits",
        "truncated",
    }:
        raise RuntimeError("machine JSON response has invalid structure")
    if exact_field(document, "contract_version", str) != "0.2.0":
        raise RuntimeError("retrieval wire mismatch")
    archive_id = exact_field(document, "archive_id", str)
    if (
        archive_id != expected_archive_id
        or UUID.fullmatch(archive_id) is None
        or type(expected_archive_id) is not str
    ):
        raise RuntimeError("retrieval response archive mismatch")
    generation_id = exact_field(document, "generation_id", str)
    if generation_id != request["generation_id"] or SHA256.fullmatch(generation_id) is None:
        raise RuntimeError("retrieval response generation mismatch")
    truncated = exact_field(document, "truncated", bool)
    validate_coverage(document, truncated)
    validate_source_context(request, source_asset_id, source_sha256)
    hits = exact_field(document, "hits", list)
    if len(hits) > request.get("limit", 20):
        raise RuntimeError("retrieval response exceeds request limit")
    threshold = request.get("min_score", -1)
    previous = None
    seen = set()
    for hit in hits:
        asset_id, score = validate_hit_context(
            hit, archive_id, source_asset_id, source_sha256, threshold
        )
        if asset_id in seen:
            raise RuntimeError("machine JSON response has invalid structure")
        seen.add(asset_id)
        ordering = (-score, asset_id)
        if previous is not None and ordering < previous:
            raise RuntimeError("retrieval response hit order mismatch")
        previous = ordering
    return hits


def validate_timeline_sequence(value):
    if value is None:
        return None
    if (
        type(value) is not str
        or not 1 <= len(value) <= 256
        or value != value.strip()
        or "\0" in value
        or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
        raise ValueError(
            "--timeline-sequence must be an unpadded 1..256-code-point "
            "Unicode scalar artifact label"
        )
    return value


def effective_history_gap(sequence_id, gap_ms):
    if sequence_id is None:
        if gap_ms is not None:
            raise ValueError("--history-gap-ms requires --timeline-sequence")
        return None
    return 30000 if gap_ms is None else gap_ms


def history_request(generation_id, asset_id, sequence_id, gap_ms):
    request = {
        "generation_id": generation_id,
        "query": {"asset_id": asset_id},
        "min_score": -1,
        "limit": 100,
    }
    if sequence_id is not None:
        request["timeline"] = {"kind": "sequence", "sequence_id": sequence_id}
        request["gap_ms"] = gap_ms
    return request


def exact_milliseconds(document, name):
    value = exact_field(document, name, int)
    if not 0 <= value <= MAX_SAFE_INTEGER:
        raise RuntimeError("machine JSON response has invalid structure")
    return value


def selected_clock(hit, timeline):
    if timeline is None:
        return None
    if timeline["kind"] == "wall":
        return hit["observed_at_ms"]
    if hit["sequence_id"] == timeline["sequence_id"]:
        return hit["sequence_position_ms"]
    return None


def validate_history_smoke(document, request, expected_archive_id, source_asset_id, source_sha256):
    if set(document) != {
        "contract_version",
        "archive_id",
        "generation_id",
        "coverage",
        "timeline",
        "history_available",
        "observations",
        "unsequenced_hits",
        "first_observed_ms",
        "last_observed_ms",
        "truncated",
        "interpretation",
    }:
        raise RuntimeError("machine JSON response has invalid structure")
    if exact_field(document, "contract_version", str) != "0.2.0":
        raise RuntimeError("retrieval wire mismatch")
    archive_id = exact_field(document, "archive_id", str)
    if archive_id != expected_archive_id or UUID.fullmatch(archive_id) is None:
        raise RuntimeError("retrieval response archive mismatch")
    generation_id = exact_field(document, "generation_id", str)
    if generation_id != request["generation_id"] or SHA256.fullmatch(generation_id) is None:
        raise RuntimeError("retrieval response generation mismatch")
    if exact_field(document, "interpretation", str) != "candidate_observations":
        raise RuntimeError("retrieval history interpretation mismatch")
    truncated = exact_field(document, "truncated", bool)
    validate_coverage(document, truncated)
    validate_source_context(request, source_asset_id, source_sha256)
    history_available = exact_field(document, "history_available", bool)
    observations = exact_field(document, "observations", list)
    unsequenced_hits = exact_field(document, "unsequenced_hits", list)
    expected_timeline = request.get("timeline")
    if expected_timeline is None:
        timeline = exact_field(document, "timeline", type(None))
    else:
        timeline = exact_field(document, "timeline", dict)
        kind = exact_field(expected_timeline, "kind", str)
        expected_fields = {"kind"}
        if kind == "sequence":
            expected_fields.add("sequence_id")
            exact_label(expected_timeline, "sequence_id", 256)
        elif kind != "wall":
            raise RuntimeError("machine JSON response has invalid structure")
        if set(expected_timeline) != expected_fields or timeline != expected_timeline:
            raise RuntimeError("retrieval response timeline mismatch")
    if not history_available:
        first_observed_ms = exact_field(document, "first_observed_ms", type(None))
        last_observed_ms = exact_field(document, "last_observed_ms", type(None))
        if first_observed_ms is not None or last_observed_ms is not None or observations:
            raise RuntimeError("unavailable history has chronological evidence")
    else:
        if timeline is None:
            raise RuntimeError("null timeline cannot provide history")
        gap_ms = request.get("gap_ms", 30000)
        first_observed_ms = exact_milliseconds(document, "first_observed_ms")
        last_observed_ms = exact_milliseconds(document, "last_observed_ms")
        if first_observed_ms > last_observed_ms:
            raise RuntimeError("machine JSON response has invalid structure")
        if not observations and (
            not truncated or len(unsequenced_hits) != request.get("limit", 20)
        ):
            raise RuntimeError("sequence-timeline smoke requires returned evidence")
        previous_end_ms = None
        first_start_ms = None
        for observation in observations:
            if type(observation) is not dict or set(observation) != {
                "start_ms",
                "end_ms",
                "max_score",
                "evidence",
            }:
                raise RuntimeError("machine JSON response has invalid structure")
            start_ms = exact_milliseconds(observation, "start_ms")
            end_ms = exact_milliseconds(observation, "end_ms")
            max_score = exact_score(observation, "max_score")
            evidence = exact_field(observation, "evidence", list)
            if (
                start_ms > end_ms
                or start_ms < first_observed_ms
                or end_ms > last_observed_ms
                or gap_ms == 0
                and start_ms != end_ms
                or not evidence
            ):
                raise RuntimeError("machine JSON response has invalid structure")
            if previous_end_ms is not None and start_ms - previous_end_ms <= gap_ms:
                raise RuntimeError("sequence-timeline smoke grouping mismatch")
            if first_start_ms is None:
                first_start_ms = start_ms
            previous_end_ms = end_ms
            previous_position_ms = None
            previous_asset_id = None
            max_matches_evidence = False
            for hit in evidence:
                asset_id, score = validate_hit_context(
                    hit,
                    archive_id,
                    source_asset_id,
                    source_sha256,
                    request.get("min_score", -1),
                )
                position_ms = selected_clock(hit, timeline)
                if position_ms is None:
                    raise RuntimeError("history evidence lacks selected clock")
                if not start_ms <= position_ms <= end_ms:
                    raise RuntimeError("machine JSON response has invalid structure")
                if previous_position_ms is not None and (
                    position_ms < previous_position_ms
                    or position_ms == previous_position_ms
                    and asset_id < previous_asset_id
                ):
                    raise RuntimeError("sequence-timeline smoke evidence order mismatch")
                if (
                    not truncated
                    and previous_position_ms is not None
                    and position_ms - previous_position_ms > gap_ms
                ):
                    raise RuntimeError("sequence-timeline smoke evidence gap mismatch")
                if score > max_score:
                    raise RuntimeError("sequence-timeline smoke max score mismatch")
                max_matches_evidence = max_matches_evidence or score == max_score
                previous_position_ms = position_ms
                previous_asset_id = asset_id
            if not truncated and (
                start_ms != selected_clock(evidence[0], timeline)
                or end_ms != selected_clock(evidence[-1], timeline)
                or not max_matches_evidence
            ):
                raise RuntimeError("sequence-timeline smoke observation mismatch")
        if not truncated and (
            first_start_ms != first_observed_ms or previous_end_ms != last_observed_ms
        ):
            raise RuntimeError("sequence-timeline smoke bounds mismatch")
    threshold = request.get("min_score", -1)
    seen = set()
    previous_unsequenced = None
    for observation in observations:
        for hit in observation["evidence"]:
            asset_id = hit["asset_id"]
            if asset_id in seen:
                raise RuntimeError("machine JSON response has invalid structure")
            seen.add(asset_id)
    for hit in unsequenced_hits:
        asset_id, score = validate_hit_context(
            hit,
            archive_id,
            source_asset_id,
            source_sha256,
            threshold,
        )
        if asset_id in seen or selected_clock(hit, timeline) is not None:
            raise RuntimeError("machine JSON response has invalid structure")
        seen.add(asset_id)
        ordering = (-score, asset_id)
        if previous_unsequenced is not None and ordering < previous_unsequenced:
            raise RuntimeError("retrieval response hit order mismatch")
        previous_unsequenced = ordering
    evidence_count = sum(len(observation["evidence"]) for observation in observations)
    if evidence_count + len(unsequenced_hits) > request.get("limit", 20):
        raise RuntimeError("retrieval response exceeds request limit")
    return history_available


def load_queries(path, checkout):
    try:
        if path.is_symlink():
            raise ValueError("--queries-json must not be a symlink")
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("--queries-json must be an existing private file") from None
    if resolved.is_relative_to(checkout):
        raise ValueError("--queries-json must be outside the server checkout")
    try:
        descriptor = os.open(resolved, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as query_file:
            metadata = os.fstat(query_file.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("--queries-json must be a regular non-symlink file")
            if metadata.st_mode & 0o077:
                raise ValueError("--queries-json must have no group or other permissions")
            if not 0 < metadata.st_size <= 64 * 1024:
                raise ValueError("--queries-json size must be 1..65536 bytes")
            raw = query_file.read(64 * 1024 + 1)
    except OSError:
        raise ValueError("--queries-json must be an existing private file") from None
    if len(raw) != metadata.st_size:
        raise ValueError("--queries-json changed while being read")
    try:
        document = parse_json_object(raw)
    except ValueError:
        raise ValueError(
            "--queries-json must be strict UTF-8 object JSON without duplicate fields "
            "or nonfinite numbers"
        ) from None
    if type(document) is not dict or set(document) != {"version", "queries"}:
        raise ValueError('--queries-json must contain exactly "version" and "queries"')
    if type(document["version"]) is not str or document["version"] != "1":
        raise ValueError('--queries-json "version" must be the string "1"')
    queries = document["queries"]
    if type(queries) is not list or not 1 <= len(queries) <= 64:
        raise ValueError('--queries-json "queries" must contain 1..64 items')
    parsed = []
    seen = set()
    for item in queries:
        if type(item) is not dict or set(item) != {"id", "text"}:
            raise ValueError('each query must contain exactly string fields "id" and "text"')
        query_id = item["id"]
        text = item["text"]
        if type(query_id) is not str or QUERY_ID.fullmatch(query_id) is None:
            raise ValueError(
                "query IDs are non-sensitive artifact labels and must be lowercase "
                "alphanumeric with optional internal hyphens"
            )
        if query_id in seen:
            raise ValueError("query IDs must be unique")
        if (
            type(text) is not str
            or not text
            or text != text.strip()
            or len(text) > 256
            or "\0" in text
            or any(0xD800 <= ord(character) <= 0xDFFF for character in text)
        ):
            raise ValueError(
                "query text must be non-empty, unpadded, at most 256 Unicode code "
                "points, and contain no NUL or surrogates"
            )
        seen.add(query_id)
        parsed.append((query_id, text))
    return parsed


def executable_prerequisites(component, environment):
    binary = component / ".build/memotrace"
    try:
        binary_mode = binary.stat().st_mode
    except OSError:
        raise ValueError("build .build/memotrace as a regular executable file first") from None
    if not stat.S_ISREG(binary_mode) or not os.access(binary, os.X_OK):
        raise ValueError("build .build/memotrace as a regular executable file first")
    docker = shutil.which("docker")
    openssl = shutil.which("openssl")
    uv = shutil.which("uv")
    if docker is None or openssl is None or uv is None:
        raise ValueError("docker, openssl, and uv 0.11.3 executables are required")
    try:
        version = run_owned([uv, "--version"], cwd=component, env=environment, timeout=10)
    except RuntimeError:
        raise ValueError("exact uv 0.11.3 executable is required") from None
    if version.returncode or not version.stdout.startswith(b"uv 0.11.3 "):
        raise ValueError("exact uv 0.11.3 executable is required")
    return binary, docker, openssl, uv


def elapsed_seconds(started):
    duration = time.monotonic() - started
    if not math.isfinite(duration) or duration < 0:
        raise RuntimeError("invalid monotonic clock duration")
    return duration


def main():
    # Convert termination into normal finally cleanup of only this owned container.
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    component = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="existing external private directory",
    )
    parser.add_argument("--threads", type=int, choices=range(1, 17), default=4)
    parser.add_argument("--batch-size", type=int, choices=range(1, 9), default=2)
    parser.add_argument(
        "--queries-json",
        type=Path,
        help="private JSON queries; IDs are non-sensitive artifact labels",
    )
    parser.add_argument(
        "--query-limit",
        type=int,
        choices=range(1, 101),
        metavar="1..100",
        default=5,
        help="maximum hits for each text query (default: 5)",
    )
    parser.add_argument(
        "--timeline-sequence",
        help="non-sensitive sequence artifact label for genuine history",
    )
    parser.add_argument(
        "--history-gap-ms",
        type=int,
        choices=range(0, 3600001),
        metavar="0..3600000",
        default=None,
        help="sequence-history gap; defaults to 30000 ms when a sequence is set",
    )
    args = parser.parse_args()
    try:
        timeline_sequence = validate_timeline_sequence(args.timeline_sequence)
        effective_gap_ms = effective_history_gap(timeline_sequence, args.history_gap_ms)
        additional_queries = (
            [] if args.queries_json is None else load_queries(args.queries_json, component.parent)
        )
    except ValueError as error:
        raise SystemExit(str(error)) from None
    output = args.output_dir.resolve()
    if (
        args.output_dir.is_symlink()
        or not output.is_dir()
        or output.is_relative_to(component.parent)
        or output.stat().st_uid != os.geteuid()
        or output.stat().st_mode & 0o077
    ):
        raise SystemExit("output directory must be existing, private and outside the checkout")
    if not args.model_dir.is_dir() or not args.manifest.is_file():
        raise SystemExit("acquire model and dataset first")
    signal.signal(signal.SIGTERM, interrupted)
    total_started = time.monotonic()
    nonce = secrets.token_hex(12)
    container_name = "memotrace-retrieval-" + nonce
    run = output / ("go-smoke-" + nonce)
    run.mkdir(mode=0o700)
    data = run / "data"
    data.mkdir(mode=0o700)
    home = run / "home"
    home.mkdir(mode=0o700)
    environment = smoke_environment(home)
    try:
        binary, docker, openssl, uv = executable_prerequisites(component, environment)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    password = secrets.token_hex(24)
    label = "memotrace.retrieval-smoke=" + nonce
    image = "postgres@sha256:74e110c41804365e3915fcc09d5e7a1eff50161aaa94d5da0e58e0cd75ae509c"
    docker_attempted = False
    server = None
    timings = {"cli_queries": {}, "http_operations": {}}

    def command(argv, *, env=None, body=None):
        try:
            result = run_owned(
                argv,
                cwd=component,
                env=env or environment,
                body=body,
                timeout=900,
            )
        except RuntimeError:
            raise RuntimeError(
                "smoke subprocess failed (diagnostics intentionally private)"
            ) from None
        if result.returncode:
            # Never print subprocess argv/environment: administrative SQL contains
            # throwaway credentials and command output can contain bootstrap tokens.
            raise RuntimeError("smoke subprocess failed (diagnostics intentionally private)")
        return result.stdout

    def save_raw(name, raw):
        write_private_bytes(run / (name + ".json"), raw)

    def save_generated(name, value):
        raw = generated_json_bytes(value)
        save_raw(name, raw)
        return raw

    def cleanup_command(argv):
        try:
            return run_owned(argv, cwd=component, env=environment, timeout=110)
        except BaseException:
            return None

    body_succeeded = False
    try:
        docker_attempted = True
        command(
            [
                docker,
                "run",
                "-d",
                "--name",
                container_name,
                "--label",
                label,
                "-e",
                "POSTGRES_PASSWORD=" + password,
                "-p",
                "127.0.0.1::5432",
                image,
            ]
        )
        for _ in range(60):
            try:
                ready = run_owned(
                    [docker, "exec", container_name, "pg_isready", "-U", "postgres"],
                    cwd=component,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except RuntimeError:
                raise RuntimeError(
                    "PostgreSQL readiness check failed (diagnostics intentionally private)"
                ) from None
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("disposable PostgreSQL did not start")
        port = (
            command(
                [
                    docker,
                    "inspect",
                    "--format",
                    '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',
                    container_name,
                ]
            )
            .decode()
            .strip()
        )
        command(
            [
                docker,
                "exec",
                container_name,
                "psql",
                "-U",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                (
                    "CREATE ROLE memotrace_runtime LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOBYPASSRLS "
                    f"PASSWORD '{password}'; CREATE ROLE memotrace_admin LOGIN "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS "
                    f"PASSWORD '{password}';"
                ),
                "-c",
                "CREATE DATABASE memotrace_smoke OWNER memotrace_admin;",
            ]
        )
        runtime_env = {
            **environment,
            "MEMOTRACE_DSN": f"postgres://memotrace_runtime:{password}@127.0.0.1:{port}/memotrace_smoke?sslmode=disable",
        }
        admin_env = {
            **environment,
            "MEMOTRACE_ADMIN_DSN": f"postgres://memotrace_admin:{password}@127.0.0.1:{port}/memotrace_smoke?sslmode=disable",
        }
        command([str(binary), "migrate"], env=admin_env)
        identity_raw = command([str(binary), "create-archive"], env=admin_env)
        identity = parse_json_object(identity_raw)
        archive = exact_field(identity, "archive_id", str)
        save_raw("archive", identity_raw)
        common = ["--archive", archive, "--data-root", str(data)]
        stage_started = time.monotonic()
        imported_raw = command(
            [
                str(binary),
                "dataset-import",
                *common,
                "--manifest",
                str(args.manifest.resolve()),
            ],
            env=runtime_env,
        )
        imported = parse_json_object(imported_raw)
        timings["dataset_import"] = elapsed_seconds(stage_started)
        imported_items = exact_field(imported, "items", list)
        if not imported_items or type(imported_items[0]) is not dict:
            raise RuntimeError("machine JSON response has invalid structure")
        source = imported_items[0]
        source_asset_id = exact_field(source, "asset_id", str)
        source_sha256 = exact_field(source, "sha256", str)
        save_raw("import", imported_raw)
        worker = json.dumps(
            [
                uv,
                "run",
                "--locked",
                "--project",
                str(component / "ml"),
                "python",
                "-m",
                "memotrace_ml.worker",
                "--model-dir",
                str(args.model_dir.resolve()),
                "--threads",
                str(args.threads),
                "--batch-size",
                str(args.batch_size),
            ]
        )
        reports = {}
        for mode in ("full", "overlap"):
            stage_started = time.monotonic()
            indexed_raw = command(
                [
                    str(binary),
                    "index",
                    *common,
                    "--mode",
                    mode,
                    "--worker-argv",
                    worker,
                ],
                env=runtime_env,
            )
            indexed = parse_json_object(indexed_raw)
            timings["index_" + mode] = elapsed_seconds(stage_started)
            generation_id = exact_field(indexed, "generation_id", str)
            coverage = exact_field(indexed, "coverage", dict)
            assets_indexed = exact_field(coverage, "assets_indexed", int)
            if assets_indexed != len(imported_items):
                raise RuntimeError("index coverage incomplete")
            save_raw("index-" + mode, indexed_raw)
            reports[mode] = indexed
            for language, text in (("en", "a screwdriver"), ("ru", "отвёртка")):
                request = {
                    "generation_id": generation_id,
                    "query": {"text": text},
                    "limit": args.query_limit,
                }
                query_started = time.monotonic()
                result_raw = command(
                    [str(binary), "search", *common, "--worker-argv", worker],
                    env=runtime_env,
                    body=json.dumps(request).encode(),
                )
                result = parse_json_object(result_raw)
                timings["cli_queries"][mode + ":" + language] = elapsed_seconds(query_started)
                if not validate_search_response(result, request, archive, None, None):
                    raise RuntimeError("genuine-model search produced no candidates")
                save_raw("cli-" + mode + "-" + language, result_raw)
            for query_id, text in additional_queries:
                request = {
                    "generation_id": generation_id,
                    "query": {"text": text},
                    "limit": args.query_limit,
                }
                query_started = time.monotonic()
                result_raw = command(
                    [str(binary), "search", *common, "--worker-argv", worker],
                    env=runtime_env,
                    body=json.dumps(request).encode(),
                )
                result = parse_json_object(result_raw)
                timing_key = mode + ":" + query_id
                timings["cli_queries"][timing_key] = timings["cli_queries"].get(
                    timing_key, 0
                ) + elapsed_seconds(query_started)
                if not validate_search_response(result, request, archive, None, None):
                    raise RuntimeError("genuine-model search produced no candidates")
                save_raw("cli-" + mode + "-query-" + query_id, result_raw)
        generation = generation_id
        request = history_request(generation, source_asset_id, timeline_sequence, effective_gap_ms)
        history_started = time.monotonic()
        history_raw = command(
            [str(binary), "history", *common, "--worker-argv", worker],
            env=runtime_env,
            body=json.dumps(request).encode(),
        )
        history = parse_json_object(history_raw)
        timings["cli_history"] = elapsed_seconds(history_started)
        history_available = validate_history_smoke(
            history, request, archive, source_asset_id, source_sha256
        )
        save_raw("cli-history", history_raw)
        cert, key = run / "cert.pem", run / "key.pem"
        command(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:P-256",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ]
        )
        key.chmod(0o600)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            address = "127.0.0.1:" + str(sock.getsockname()[1])
        origin = "https://" + address
        try:
            server = subprocess.Popen(
                [
                    str(binary),
                    "serve",
                    "--data-root",
                    str(data),
                    "--listen",
                    address,
                    "--cert",
                    str(cert),
                    "--key",
                    str(key),
                    "--worker-argv",
                    worker,
                ],
                cwd=component,
                env=runtime_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError(
                "TLS service failed to start (diagnostics intentionally private)"
            ) from None
        tls = ssl.create_default_context(cafile=cert)
        http_opener = proxy_free_https_opener(tls)

        def http(path, payload=None, token=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(
                origin + path,
                data=None if payload is None else json.dumps(payload).encode(),
                headers=headers,
            )
            with http_opener.open(req, timeout=90) as response:
                if (
                    response.headers["Cache-Control"] != "no-store"
                    or response.headers["X-Content-Type-Options"] != "nosniff"
                ):
                    raise RuntimeError("HTTP privacy headers missing")
                return response.read()

        for _ in range(100):
            try:
                health = parse_json_object(http("/healthz"))
                health_version = exact_field(health, "contract_version", str)
                break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError("TLS service exited") from None
                time.sleep(0.05)
        else:
            raise RuntimeError("TLS service unavailable")
        pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
        invitation = parse_json_object(
            command(
                [
                    str(binary),
                    "invite",
                    "--archive",
                    archive,
                    "--server-url",
                    origin,
                    "--cert",
                    str(cert),
                    "--expected-pin",
                    pin,
                ],
                env=admin_env,
            )
        )
        invitation_token = exact_field(invitation, "invitation_token", str)
        pair = parse_json_object(
            http(
                "/v1/pairing/redeem",
                {
                    "invitation_token": invitation_token,
                    "device_name": "public-model-smoke",
                },
            )
        )
        pair_version = exact_field(pair, "contract_version", str)
        token = exact_field(pair, "device_token", str)
        if health_version != "0.1.0" or pair_version != "0.1.0":
            raise RuntimeError("legacy wire changed")
        for operation in ("search", "history"):
            payload = request
            if operation == "search" and "gap_ms" in request:
                payload = {key: value for key, value in request.items() if key != "gap_ms"}
            http_started = time.monotonic()
            result_raw = http(f"/v1/archives/{archive}/{operation}", payload, token)
            result = parse_json_object(result_raw)
            timings["http_operations"][operation] = elapsed_seconds(http_started)
            if exact_field(result, "contract_version", str) != "0.2.0":
                raise RuntimeError("retrieval wire mismatch")
            if operation == "search":
                validate_search_response(result, payload, archive, source_asset_id, source_sha256)
            else:
                if (
                    validate_history_smoke(result, request, archive, source_asset_id, source_sha256)
                    != history_available
                ):
                    raise RuntimeError("CLI and HTTP history availability mismatch")
            save_raw("http-" + operation, result_raw)
        original = http(
            f"/v1/archives/{archive}/search/assets/{source_asset_id}/original",
            token=token,
        )
        if hashlib.sha256(original).hexdigest() != source_sha256:
            raise RuntimeError("original-byte mismatch")
        body_succeeded = True
    finally:
        active_error = sys.exc_info()[0] is not None
        cleanup_failed = False
        tls_shutdown = None
        if server is not None:
            try:
                if server.poll() is not None:
                    raise RuntimeError("TLS service exited before graceful shutdown")
                _, _, signaled = terminate_owned(
                    server, graceful_seconds=110, kill_seconds=10, expected_status=0
                )
                if not signaled:
                    raise RuntimeError("TLS service did not receive graceful termination")
                tls_shutdown = "sigterm-exit-0"
            except BaseException:
                cleanup_failed = True
        if docker_attempted:
            inspected = cleanup_command(
                [
                    docker,
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "memotrace.retrieval-smoke"}}',
                    container_name,
                ]
            )
            if inspected is None:
                cleanup_failed = True
            elif inspected.returncode == 0:
                try:
                    owned = inspected.stdout.decode("utf-8").strip()
                except UnicodeError:
                    cleanup_failed = True
                else:
                    if owned != nonce:
                        cleanup_failed = True
                    else:
                        stopped = cleanup_command([docker, "stop", "--time=10", container_name])
                        if stopped is None or stopped.returncode:
                            cleanup_command([docker, "rm", "-f", "-v", container_name])
                            cleanup_failed = True
                        else:
                            removed = cleanup_command([docker, "rm", "-v", container_name])
                            if removed is None or removed.returncode:
                                cleanup_failed = True
            else:
                listed = cleanup_command(
                    [
                        docker,
                        "ps",
                        "-a",
                        "--filter",
                        "name=^/" + container_name + "$",
                        "--format",
                        "{{.Names}}",
                    ]
                )
                if listed is None or listed.returncode:
                    cleanup_failed = True
                else:
                    try:
                        names = listed.stdout.decode("utf-8").splitlines()
                    except UnicodeError:
                        cleanup_failed = True
                    else:
                        if container_name in names:
                            cleanup_failed = True
        if cleanup_failed and body_succeeded and not active_error:
            raise RuntimeError("smoke cleanup failed (diagnostics intentionally private)")

    timings["total"] = elapsed_seconds(total_started)
    summary = {
        "assets": len(imported_items),
        "index": reports,
        "worker_runtime": {"threads": args.threads, "batch_size": args.batch_size},
        "cli_languages": ["en", "ru"],
        "additional_query_ids": [query_id for query_id, _ in additional_queries],
        "query_limit": args.query_limit,
        "timings_seconds": timings,
        "timeline": {
            "kind": "sequence" if timeline_sequence is not None else None,
            "sequence_id": timeline_sequence,
            "gap_ms": effective_gap_ms,
        },
        "http_pair_search_history_original": "passed",
        "tls_service_shutdown": tls_shutdown,
        "history_available": history_available,
        "artifacts": str(run),
    }
    summary_raw = save_generated("summary", summary)
    print(summary_raw.decode("utf-8"), end="")


if __name__ == "__main__":
    main()
