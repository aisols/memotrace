"""Focused model-free tests for the external genuine-model smoke helper."""

import decimal
import importlib.util
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest


def load_smoke() -> ModuleType:
    path = Path(__file__).with_name("retrieval-smoke.py")
    spec = importlib.util.spec_from_file_location("retrieval_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMOKE = load_smoke()
ARCHIVE = "11111111-1111-1111-1111-111111111111"
OTHER_ARCHIVE = "22222222-2222-2222-2222-222222222222"
SOURCE_ASSET = "33333333-3333-3333-3333-333333333333"
ASSET_A = "44444444-4444-4444-4444-444444444444"
ASSET_B = "55555555-5555-5555-5555-555555555555"
GENERATION = "9" * 64


def hit(
    archive: str,
    asset: str = ASSET_A,
    score: str = "0.5",
    sequence_id: str | None = None,
    sequence_position_ms: int | None = None,
) -> dict[str, object]:
    return {
        "asset_id": asset,
        "source_kind": "dataset",
        "frame_id": None,
        "dataset": {"name": "synthetic", "version": "1", "item_id": asset},
        "sha256": ("a" if asset == ASSET_A else "b") * 64,
        "score": decimal.Decimal(score),
        "region": {"kind": "full", "box": [0, 0, 1, 1]},
        "observed_at_ms": None,
        "sequence_id": sequence_id,
        "sequence_position_ms": sequence_position_ms,
        "original_path": f"/v1/archives/{archive}/search/assets/{asset}/original",
    }


def response(request: dict[str, object]) -> dict[str, object]:
    return {
        "contract_version": "0.2.0",
        "archive_id": ARCHIVE,
        "generation_id": request["generation_id"],
        "coverage": {
            "assets_total": 1,
            "assets_indexed": 1,
            "pending": 0,
            "failed": 0,
            "regions_indexed": 1,
        },
        "hits": [hit(ARCHIVE)],
        "truncated": False,
    }


def history_response(request: dict[str, object]) -> dict[str, object]:
    return {
        "contract_version": "0.2.0",
        "archive_id": ARCHIVE,
        "generation_id": request["generation_id"],
        "coverage": {
            "assets_total": 2,
            "assets_indexed": 2,
            "pending": 0,
            "failed": 0,
            "regions_indexed": 2,
        },
        "timeline": request.get("timeline"),
        "history_available": False,
        "observations": [],
        "unsequenced_hits": [],
        "first_observed_ms": None,
        "last_observed_ms": None,
        "truncated": False,
        "interpretation": "candidate_observations",
    }


def sequence_history(request: dict[str, object]) -> dict[str, object]:
    document = history_response(request)
    evidence = hit(ARCHIVE, sequence_id="sequence-a", sequence_position_ms=10)
    document.update(
        {
            "history_available": True,
            "observations": [
                {
                    "start_ms": 10,
                    "end_ms": 10,
                    "max_score": decimal.Decimal("0.5"),
                    "evidence": [evidence],
                }
            ],
            "first_observed_ms": 10,
            "last_observed_ms": 10,
        }
    )
    return document


@pytest.mark.parametrize(
    "mismatch", ["archive", "generation", "coverage", "limit", "threshold", "hit-shape"]
)
def test_full_search_validation_rejects_context_and_shape_drift(mismatch: str) -> None:
    request: dict[str, object] = {
        "generation_id": GENERATION,
        "query": {"text": "screwdriver"},
        "limit": 1,
    }
    document = response(request)
    if mismatch == "archive":
        document["archive_id"] = OTHER_ARCHIVE
    elif mismatch == "generation":
        document["generation_id"] = "8" * 64
    elif mismatch == "coverage":
        document["coverage"] = {
            "assets_total": 0,
            "assets_indexed": 0,
            "pending": 0,
            "failed": 0,
            "regions_indexed": 0,
        }
    elif mismatch == "limit":
        archive = str(document["archive_id"])
        document["hits"] = [hit(archive), hit(archive, ASSET_B, "0.4")]
    elif mismatch == "threshold":
        request["min_score"] = decimal.Decimal("0.6")
    else:
        first = document["hits"]
        assert isinstance(first, list) and isinstance(first[0], dict)
        first[0].pop("region")
    with pytest.raises(RuntimeError):
        SMOKE.validate_search_response(document, request, ARCHIVE, None, None)


def test_full_search_validation_accepts_exact_request_and_source_context() -> None:
    request: dict[str, object] = {
        "generation_id": GENERATION,
        "query": {"asset_id": SOURCE_ASSET},
        "limit": 1,
        "min_score": decimal.Decimal("0.5"),
    }
    document = response(request)
    assert SMOKE.validate_search_response(document, request, ARCHIVE, SOURCE_ASSET, "c" * 64)
    with pytest.raises(RuntimeError, match="self leak"):
        SMOKE.validate_search_response(document, request, ARCHIVE, SOURCE_ASSET, "a" * 64)


@pytest.mark.parametrize("mismatch", ["contract", "archive", "coverage", "interpretation", "extra"])
def test_history_validation_rejects_prior_false_acceptance(mismatch: str) -> None:
    request: dict[str, object] = {
        "generation_id": GENERATION,
        "query": {"text": "screwdriver"},
        "min_score": decimal.Decimal("0.1"),
    }
    document = history_response(request)
    if mismatch == "contract":
        document["contract_version"] = "0.1.0"
    elif mismatch == "archive":
        document["archive_id"] = OTHER_ARCHIVE
    elif mismatch == "coverage":
        document["coverage"] = {}
    elif mismatch == "interpretation":
        document["interpretation"] = "object_history"
    else:
        document["extra"] = True
    with pytest.raises(RuntimeError):
        SMOKE.validate_history_smoke(document, request, ARCHIVE, None, None)


def test_history_validation_accepts_unavailable_selected_sequence() -> None:
    request: dict[str, object] = {
        "generation_id": GENERATION,
        "query": {"asset_id": SOURCE_ASSET},
        "min_score": decimal.Decimal("0.4"),
        "limit": 1,
        "timeline": {"kind": "sequence", "sequence_id": "sequence-a"},
        "gap_ms": 30,
    }
    document = history_response(request)
    document["unsequenced_hits"] = [hit(ARCHIVE)]
    assert not SMOKE.validate_history_smoke(document, request, ARCHIVE, SOURCE_ASSET, "c" * 64)


def test_history_validation_accepts_exact_sequence_history() -> None:
    request: dict[str, object] = {
        "generation_id": GENERATION,
        "query": {"asset_id": SOURCE_ASSET},
        "min_score": decimal.Decimal("0.4"),
        "limit": 1,
        "timeline": {"kind": "sequence", "sequence_id": "sequence-a"},
        "gap_ms": 30,
    }
    assert SMOKE.validate_history_smoke(
        sequence_history(request), request, ARCHIVE, SOURCE_ASSET, "c" * 64
    )


@pytest.mark.parametrize("mismatch", ["limit", "threshold", "source-id", "source-hash", "hit"])
def test_history_validation_rejects_request_and_evidence_drift(mismatch: str) -> None:
    request: dict[str, object] = {
        "generation_id": GENERATION,
        "query": {"asset_id": SOURCE_ASSET},
        "min_score": decimal.Decimal("0.4"),
        "limit": 1,
        "timeline": {"kind": "sequence", "sequence_id": "sequence-a"},
        "gap_ms": 30,
    }
    document = sequence_history(request)
    source_hash = "c" * 64
    if mismatch == "limit":
        observation = document["observations"]
        assert isinstance(observation, list) and isinstance(observation[0], dict)
        observation[0]["evidence"].append(hit(ARCHIVE, ASSET_B, "0.4", "sequence-a", 10))
    elif mismatch == "threshold":
        request["min_score"] = decimal.Decimal("0.6")
    else:
        observations = document["observations"]
        assert isinstance(observations, list) and isinstance(observations[0], dict)
        evidence = observations[0]["evidence"]
        assert isinstance(evidence, list) and isinstance(evidence[0], dict)
        if mismatch == "source-id":
            evidence[0]["asset_id"] = SOURCE_ASSET
            evidence[0]["original_path"] = (
                f"/v1/archives/{ARCHIVE}/search/assets/{SOURCE_ASSET}/original"
            )
        elif mismatch == "source-hash":
            source_hash = "a" * 64
        else:
            evidence[0].pop("region")
    with pytest.raises(RuntimeError):
        SMOKE.validate_history_smoke(document, request, ARCHIVE, SOURCE_ASSET, source_hash)


def test_external_smoke_environment_is_exact_private_offline_allowlist(
    tmp_path: Path,
) -> None:
    environment = SMOKE.smoke_environment(tmp_path)
    assert environment == {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(tmp_path),
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
    forbidden = {
        "PGPASSWORD",
        "PGPASSFILE",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "HF_TOKEN",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "PYTHONPATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    }
    assert forbidden.isdisjoint(environment)


def test_loopback_https_opener_ignores_ambient_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://198.51.100.10:8080")
    monkeypatch.setenv("https_proxy", "http://198.51.100.11:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    connected: list[tuple[str, int]] = []

    def reject_connection(
        address: tuple[str, int],
        timeout: float | object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        connected.append(address)
        raise OSError("synthetic direct connection failure")

    monkeypatch.setattr(socket, "create_connection", reject_connection)
    tls = ssl.create_default_context()
    opener = SMOKE.proxy_free_https_opener(tls)
    with pytest.raises(OSError):
        opener.open("https://127.0.0.1:4443/healthz", timeout=0.1)
    assert connected == [("127.0.0.1", 4443)]
    assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED


def test_tls_shutdown_requires_sigterm_exit_zero(tmp_path: Path) -> None:
    marker = tmp_path / "term"
    ready = tmp_path / "ready"
    source = (
        "import pathlib,signal,sys,time; "
        f"marker=pathlib.Path({str(marker)!r}); "
        "signal.signal(signal.SIGTERM,lambda *_:(marker.write_text('term'),sys.exit(0))); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); "
        "time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", source],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 2
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    _, _, signaled = SMOKE.terminate_owned(process, 1, 1, expected_status=0)
    assert signaled and marker.read_text() == "term"
    failed = subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(7)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    failed.wait(timeout=2)
    with pytest.raises(RuntimeError, match="unexpected graceful status"):
        SMOKE.terminate_owned(failed, expected_status=0)


def test_forced_owned_group_cleanup_fails_and_kills_descendant(tmp_path: Path) -> None:
    child_pid = tmp_path / "child-pid"
    child = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    source = (
        "import pathlib,signal,subprocess,sys,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid)); "
        "time.sleep(60)"
    )
    with pytest.raises(RuntimeError, match="forced termination"):
        SMOKE.run_owned(
            [sys.executable, "-c", source],
            cwd=tmp_path,
            env=SMOKE.smoke_environment(tmp_path),
            timeout=0.2,
            graceful_seconds=0.1,
            kill_seconds=1,
        )
    pid = int(child_pid.read_text())
    deadline = time.monotonic() + 2
    process_stat = Path(f"/proc/{pid}/stat")
    while time.monotonic() < deadline:
        try:
            stat_fields = process_stat.read_text().split()
        except (FileNotFoundError, ProcessLookupError):
            return
        if stat_fields[2] == "Z":
            break
        time.sleep(0.01)
    try:
        assert process_stat.read_text().split()[2] == "Z"
    except (FileNotFoundError, ProcessLookupError):
        pass
