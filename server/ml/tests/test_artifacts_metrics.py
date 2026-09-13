"""Synthetic integrity, judgment, ranking, and acquisition boundary regressions."""

from pathlib import Path

import numpy as np
import pytest

from memotrace_ml import summary
from memotrace_ml.acquire import download
from memotrace_ml.benchmark import (
    QUERIES,
    REPORT_VERSION,
    RRF_K,
    aggregate_queries,
    content_corpus,
    content_judgments,
    fusion_query_result,
    language_evaluation_metadata,
    language_query_description,
    metrics,
    rank_assets,
    reciprocal_rank_fusion,
    validate_query_profile,
)
from memotrace_ml.checkpoints import DEFAULT_CHECKPOINT, Checkpoint
from memotrace_ml.common import (
    JSON,
    file_digest,
    list_value,
    object_value,
    parse_json,
    write_json,
)
from memotrace_ml.dataset import Item, load_items, optional_time
from memotrace_ml.model import verify_model
from memotrace_ml.openimages import CLASSES, labels_from
from memotrace_ml.summary import macro_eligibility


def test_unknowns_not_negatives_and_recall_is_fraction() -> None:
    result = metrics(
        ["unknown", "no", "a", "b", "c"], {"a": True, "b": True, "c": True, "no": False}
    )
    assert result["judged_candidates"] == 4
    assert result["unknown_candidates"] == 1
    assert result["unknown_in_corpus_top1"] == 1
    assert result["Hit@1"] == 0
    assert result["Hit@5"] == 1 and result["Recall@5"] == 1
    assert result["AP"] == pytest.approx((1 / 2 + 2 / 3 + 3 / 4) / 3)
    many = metrics([str(i) for i in range(10)], {str(i): True for i in range(10)})
    assert many["Recall@5"] == 0.5
    assert metrics(["no"], {"no": False})["AP"] is None
    with pytest.raises(ValueError):
        metrics(["a", "a"], {"a": True})


def test_max_per_asset_and_same_image_exclusion_before_ranking() -> None:
    vectors = {
        "query-source": np.asarray([[1, 0], [1, 0]], dtype=np.float32),
        "b": np.asarray([[0, 1], [0.8, 0.6]], dtype=np.float32),
        "a": np.asarray([[0.8, 0.6]], dtype=np.float32),
    }
    ranked = rank_assets(
        vectors,
        np.asarray([1, 0], dtype=np.float32),
        {"query-source": "source-hash", "a": "a-hash", "b": "b-hash"},
        "source-hash",
    )
    assert [identity for identity, _ in ranked] == ["a", "b"]
    assert ranked[1][1] == pytest.approx(0.8)


def test_reciprocal_rank_fusion_order_and_scores() -> None:
    fused = reciprocal_rank_fusion(["a", "b", "c"], ["a", "b", "c"])
    assert [identity for identity, _ in fused] == ["a", "b", "c"]
    assert [score for _, score in fused] == pytest.approx(
        [2 / (RRF_K + 1), 2 / (RRF_K + 2), 2 / (RRF_K + 3)]
    )


def test_reciprocal_rank_fusion_ties_break_by_identity() -> None:
    fused = reciprocal_rank_fusion(["b", "a"], ["a", "b"])
    assert fused[0][1] == fused[1][1]
    assert [identity for identity, _ in fused] == ["a", "b"]


@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        (["a", "a"], ["a", "b"], "duplicate"),
        (["a", "b"], ["a", "a"], "duplicate"),
        (["a", "b"], ["a", "c"], "candidate sets differ"),
    ],
)
def test_reciprocal_rank_fusion_rejects_duplicates_and_mismatched_candidates(
    first: list[str], second: list[str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        reciprocal_rank_fusion(first, second)


def test_fusion_query_metadata_scores_and_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter((10.0, 10.005))
    monkeypatch.setattr("memotrace_ml.benchmark.time.monotonic", lambda: next(clock))
    result = fusion_query_result(
        "class",
        "full",
        {"a": True, "b": False},
        ([("a", 0.9), ("b", 0.8)], 0.2, 0.03),
        ([("b", 0.7), ("a", 0.6)], 0.3, 0.04),
    )
    query = object_value(result["query"])
    assert query == {
        "kind": "ranking_fusion",
        "method": "reciprocal_rank_fusion",
        "k": 60,
        "component_query_ids": ["class:en", "class:ru"],
        "automatic_translation": False,
    }
    assert result["ranking_score_kind"] == "rrf"
    ranking = [object_value(value) for value in list_value(result["ranking"])]
    assert [value["id"] for value in ranking] == ["a", "b"]
    assert all("rrf_score" in value and "score" not in value for value in ranking)
    timing = object_value(result["timing"])
    assert timing["component_embedding_seconds"] == {"en": 0.2, "ru": 0.3}
    assert timing["component_ranking_seconds"] == {"en": 0.03, "ru": 0.04}
    assert timing["additional_fusion_seconds"] == pytest.approx(0.005)
    assert timing["accounted_total_seconds"] == pytest.approx(0.575)


def test_curated_language_and_report_metadata_preserve_v2_summary_compatibility() -> None:
    english = language_query_description("class", "en", "translated query")
    russian = language_query_description("class", "ru", "russian query")
    assert english["pair_role"] == "manually_curated_english_evaluation_translation"
    assert english["automatic_translation"] is False
    assert english["paired_query_id"] == "class:ru"
    assert russian["pair_role"] == "manually_curated_russian_evaluation_query"
    assert russian["paired_query_id"] == "class:en"
    metadata = language_evaluation_metadata()
    assert metadata["query_groups"] == ["en", "ru", "fusion"]
    assert metadata["fusion"] == {"method": "reciprocal_rank_fusion", "k": 60}
    assert REPORT_VERSION == "openimages-retrieval-pilot-v3"
    assert macro_eligibility("openimages-retrieval-pilot-v2") == "both-polarities-primary"
    assert macro_eligibility(REPORT_VERSION) == "both-polarities-primary"


def test_benchmark_queries_exactly_match_verified_ground_truth_profile() -> None:
    assert tuple(QUERIES) == tuple(CLASSES.values())
    assert QUERIES["/m/04dr76w"] == {
        "en": "a photo of a bottle",
        "ru": "фотография бутылки",
    }
    assert QUERIES["/m/02jvh9"] == {
        "en": "a photo of a mug",
        "ru": "фотография кружки",
    }
    assert QUERIES["/m/050k8"] == {
        "en": "a photo of a mobile phone",
        "ru": "фотография мобильного телефона",
    }
    ground_truth: dict[str, JSON] = {mid: {} for mid in CLASSES.values()}
    validate_query_profile(ground_truth)
    validate_query_profile({mid: {} for mid in sorted(CLASSES.values())})
    mobile_phone_mid = CLASSES["Mobile phone"]
    ground_truth.pop(mobile_phone_mid)
    with pytest.raises(ValueError, match="query profile mismatch"):
        validate_query_profile(ground_truth)


def test_summary_reads_historical_v2_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "historical-v2.json"
    write_json(
        report,
        {"version": "openimages-retrieval-pilot-v2", "model_identity": {}},
    )
    monkeypatch.setattr("sys.argv", ["summary", "--report", str(report)])
    summary.main()
    safe = object_value(parse_json(capsys.readouterr().out.encode()))
    assert safe["macro_eligibility"] == "both-polarities-primary"
    assert "language_evaluation" not in safe


def test_machine_and_unknown_labels_are_not_human_negatives(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_text(
        "ImageID,Source,LabelName,Confidence\n"
        "a,verification,/m/01bms0,1\n"
        "b,crowdsource-verification,/m/01bms0,0\n"
        "c,machine,/m/01bms0,0\n",
        encoding="utf-8",
    )
    labels = labels_from(path)["/m/01bms0"]
    assert labels == {"a": True, "b": False}
    assert labels.get("unknown") is None


def make_manifest(root: Path, path: str = "synthetic.jpg") -> dict[str, JSON]:
    image = root / "synthetic.jpg"
    image.write_bytes(b"synthetic integrity-only bytes, not a JPEG")
    return {
        "version": "1",
        "dataset": {
            "name": "synthetic",
            "version": "1",
            "source": "test-only",
            "license": "AGPL-3.0-only",
        },
        "items": [Item("synthetic", path, file_digest(image), image.stat().st_size).json()],
    }


def test_manifest_integrity_and_null_clocks(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_json(path, make_manifest(tmp_path))
    _, items = load_items(path)
    assert items[0].observed_at_ms is None
    assert items[0].sequence_id is None and items[0].sequence_position_ms is None
    (tmp_path / "synthetic.jpg").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        load_items(path)


@pytest.mark.parametrize(
    "relative",
    ["../escape.jpg", "/absolute.jpg", "x/../../escape.jpg", "x\\escape.jpg", "./synthetic.jpg"],
)
def test_manifest_path_traversal(tmp_path: Path, relative: str) -> None:
    path = tmp_path / "manifest.json"
    write_json(path, make_manifest(tmp_path, relative))
    with pytest.raises(ValueError):
        load_items(path)


@pytest.mark.parametrize("value", [True, -1, 2**53, 0.5, "0"])
def test_invalid_sequence_times(value: JSON) -> None:
    with pytest.raises(ValueError):
        optional_time(value)


def test_real_sequence_fields_roundtrip_without_inventing_wall_time(tmp_path: Path) -> None:
    (tmp_path / "synthetic.jpg").write_bytes(b"test-only")
    manifest = make_manifest(tmp_path)
    image = tmp_path / "synthetic.jpg"
    manifest["items"] = [
        Item(
            "test",
            "synthetic.jpg",
            file_digest(image),
            image.stat().st_size,
            sequence_id="synthetic-sequence",
            sequence_position_ms=250,
        ).json()
    ]
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    _, items = load_items(path)
    assert items[0].sequence_position_ms == 250 and items[0].observed_at_ms is None


def test_model_hash_verification_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"test-only, not model weights")
    pinned: dict[str, JSON] = {
        "files": {
            "model.safetensors": {
                "sha256": file_digest(weights),
                "byte_length": weights.stat().st_size,
            }
        }
    }

    def approve_synthetic(manifest: dict[str, JSON]) -> Checkpoint:
        assert manifest == pinned
        return DEFAULT_CHECKPOINT

    monkeypatch.setattr("memotrace_ml.model.checkpoint_for_manifest", approve_synthetic)
    write_json(tmp_path / "manifest.json", pinned)
    assert verify_model(tmp_path) == pinned
    weights.write_bytes(b"x" * weights.stat().st_size)
    with pytest.raises(ValueError, match="digest"):
        verify_model(tmp_path)


def test_acquisition_rejects_cache_tampering_and_insecure_sources(tmp_path: Path) -> None:
    target = tmp_path / "artifact"
    target.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="mismatch"):
        download("https://huggingface.co/model", target, 100, "0" * 64)
    with pytest.raises(ValueError):
        download("http://example.invalid/model", target, 100)


def test_source_content_alias_excluded_and_candidates_deduplicated_before_scoring() -> None:
    vectors = {
        # Deliberately wrong dimensions: scoring any excluded/deduplicated alias fails.
        "source": np.asarray([[1, 0, 0]], dtype=np.float32),
        "source-alias": np.asarray([[1, 0, 0]], dtype=np.float32),
        "a": np.asarray([[0.8, 0.6]], dtype=np.float32),
        "a-alias": np.asarray([[1, 0, 0]], dtype=np.float32),
    }
    hashes = {"source": "s", "source-alias": "s", "a": "a", "a-alias": "a"}
    ranked = rank_assets(vectors, np.asarray([1, 0], dtype=np.float32), hashes, "s")
    assert [identity for identity, _ in ranked] == ["a"]
    assert ranked[0][1] == pytest.approx(0.8)


def test_alias_judgments_merge_known_unknown_but_reject_contradictions() -> None:
    items = [Item("b", "b.jpg", "same", 10), Item("a", "a.jpg", "same", 10)]
    unique, groups = content_corpus(items)
    assert len(unique) == 1 and unique[0].id == "a"
    assert content_judgments(groups, {"a": None, "b": True}) == {"a": True}
    with pytest.raises(ValueError, match="conflicting"):
        content_judgments(groups, {"a": False, "b": True})


def test_zero_negative_class_excluded_from_primary_macro() -> None:
    queries: list[JSON] = [
        {"query_id": "trivial:en", "mode": "full", "metrics": metrics(["p"], {"p": True})},
        {
            "query_id": "judged:en",
            "mode": "full",
            "metrics": metrics(["n", "p"], {"n": False, "p": True}),
        },
    ]
    primary = object_value(aggregate_queries(queries, both_polarities=True)["full:en"])
    secondary = object_value(aggregate_queries(queries, both_polarities=False)["full:en"])
    assert primary["AP"] == 0.5 and primary["eligible_queries"] == 1
    assert primary["excluded_queries"] == [{"query_id": "trivial:en", "reason": "no_negative"}]
    assert secondary["AP"] == 0.75 and secondary["eligible_queries"] == 2


def test_macro_aggregation_includes_fusion_for_both_index_modes() -> None:
    queries: list[JSON] = [
        {
            "query_id": "class:fusion",
            "mode": mode,
            "metrics": metrics(["p", "n"], {"p": True, "n": False}),
        }
        for mode in ("full", "overlap")
    ]
    aggregate = aggregate_queries(queries, both_polarities=True)
    for mode in ("full", "overlap"):
        fusion = object_value(aggregate[mode + ":fusion"])
        assert fusion["query_count"] == 1
        assert fusion["eligible_queries"] == 1
        assert fusion["AP"] == 1.0
