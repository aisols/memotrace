"""Model-free runtime-bound regressions for the Base224 performance matrix."""

from pathlib import Path

import pytest

from memotrace_ml import benchmark
from memotrace_ml.model import validate_runtime_bounds


@pytest.mark.parametrize(
    ("threads", "batch_size"),
    [(threads, batch_size) for threads in (1, 2, 4, 8, 16) for batch_size in (1, 2, 4, 8)],
)
def test_base224_performance_matrix_is_valid(threads: int, batch_size: int) -> None:
    validate_runtime_bounds(threads, batch_size)


@pytest.mark.parametrize(
    ("threads", "batch_size"),
    [(0, 1), (17, 1), (1, 0), (1, 9), (False, 1), (True, 1), (1, False), (1, True)],
)
def test_invalid_runtime_bounds_raise_generic_value_error(threads: int, batch_size: int) -> None:
    with pytest.raises(ValueError, match="^invalid runtime bounds$"):
        validate_runtime_bounds(threads, batch_size)


def test_benchmark_rejects_runtime_bounds_before_filesystem_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_filesystem_work(path: Path) -> Path:
        raise AssertionError(f"unexpected filesystem work: {path}")

    monkeypatch.setattr(benchmark, "external_root", unexpected_filesystem_work)
    with pytest.raises(ValueError, match="^invalid runtime bounds$"):
        benchmark.run(
            Path("missing-model"),
            Path("missing-data"),
            Path("missing-output/report.json"),
            threads=17,
            batch_size=1,
            image_queries=False,
            gt_query_crop=False,
        )
