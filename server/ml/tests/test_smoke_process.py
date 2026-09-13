"""Model-free live-smoke environment and owned-process cleanup checks."""

import sys
import time
from pathlib import Path

import pytest

from memotrace_ml.smoke import run_owned_worker, smoke_environment


def live_process(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split()[2]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state != "Z"


def test_live_smoke_environment_is_an_exact_offline_allowlist(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    environment = smoke_environment(home)
    assert environment == {
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
    forbidden = {
        "PGPASSWORD",
        "PGPASSFILE",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "HF_TOKEN",
        "HTTPS_PROXY",
        "NO_PROXY",
        "PYTHONPATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    }
    assert forbidden.isdisjoint(environment)


def test_live_smoke_timeout_requests_sigterm_before_failure(tmp_path: Path) -> None:
    marker = tmp_path / "term"
    source = (
        "import pathlib,signal,sys,time; "
        f"marker=pathlib.Path({str(marker)!r}); "
        "signal.signal(signal.SIGTERM,lambda *_:(marker.write_text('term'),sys.exit(0))); "
        "time.sleep(60)"
    )
    with pytest.raises(RuntimeError, match="timed out after graceful"):
        run_owned_worker(
            [sys.executable, "-c", source],
            b"",
            smoke_environment(tmp_path),
            timeout=0.1,
            graceful_seconds=1,
            kill_seconds=1,
        )
    assert marker.read_text() == "term"


def test_live_smoke_forced_cleanup_fails_and_kills_descendant(tmp_path: Path) -> None:
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
        run_owned_worker(
            [sys.executable, "-c", source],
            b"",
            smoke_environment(tmp_path),
            timeout=0.2,
            graceful_seconds=0.1,
            kill_seconds=1,
        )
    pid = int(child_pid.read_text())
    deadline = time.monotonic() + 2
    while live_process(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not live_process(pid)
