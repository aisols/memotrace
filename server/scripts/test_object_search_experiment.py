"""Real-core end-to-end synthetic runner, artifact, CLI and metric regressions; no network."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import io
import os
import socket
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Self, cast

import numpy as np
import pytest
import torch
from memotrace_ml import identity as runtime_identity
from memotrace_ml.checkpoints import DEFAULT_CHECKPOINT
from memotrace_ml.common import JSON, canonical, fingerprint, list_value, object_value, parse_json
from memotrace_ml.dataset import Item
from memotrace_ml.numbers import ExactDecimal
from memotrace_ml.openimages import CLASS_PROFILE, METADATA
from numpy.typing import NDArray
from PIL import Image

from scripts import object_search_experiment as experiment
from scripts import object_search_vision as vision
from scripts import verify_object_search as verifier


@pytest.fixture(autouse=True)
def artifact_umask() -> Iterator[None]:
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("synthetic runner must never use network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def unit(color: int, dimension: int, *, instance: bool = False) -> NDArray[np.float32]:
    # Semantic query ranks 40 before 80. Independent descriptors rank 80 before 40.
    pair = (
        (1.0, 0.0)
        if color == 120
        else ((0.6, 0.8) if color == 40 else (1.0, 0.0))
        if instance
        else ((0.8, 0.6) if color == 40 else (0.6, 0.8))
    )
    vector = np.zeros(dimension, dtype=np.float32)
    vector[:2] = pair
    return vector


def color(image: Image.Image) -> int:
    return int(np.asarray(image)[0, 0, 0])


class FakeSemantic:
    identity: dict[str, JSON] = {"model": "synthetic-semantic"}
    model_fingerprint = "synthetic-semantic"
    dimension = 768

    def __init__(self) -> None:
        self.batches: list[int] = []

    def images(self, images: list[Image.Image]) -> list[list[float]]:
        self.batches.append(len(images))
        assert 1 <= len(images) <= 2
        return [unit(color(image), self.dimension).tolist() for image in images]


class FakeVision:
    identity: dict[str, JSON] = {"model": "synthetic-descriptor"}
    model_fingerprint = "synthetic-descriptor"
    last_proposal_counts: vision.ProposalCounts | None = None

    def __init__(self) -> None:
        self.detected: list[int] = []
        self.described: list[int] = []
        self.empty_colors: set[int] = set()

    def proposals(self, image: Image.Image) -> tuple[vision.Proposal, ...]:
        value = color(image)
        self.detected.append(value)
        proposals = (
            ()
            if value in self.empty_colors
            else (
                vision.Proposal(
                    (0.0, 0.0, 1.0, 1.0),
                    (0, 0, *image.size),
                    0.9,
                    1,
                    0,
                    image.size,
                ),
            )
        )
        self.last_proposal_counts = vision.ProposalCounts(
            100, 100 - len(proposals), 0, 0, 0, len(proposals)
        )
        return proposals

    def descriptors(self, images: Sequence[Image.Image]) -> NDArray[np.float32]:
        assert 1 <= len(images) <= 2
        self.described.extend(color(image) for image in images)
        return np.stack([unit(color(image), 384, instance=True) for image in images])


def image_json(
    root: Path, image_id: str, value: int, timestamp: int | None = None, sequence: str = "episode"
) -> dict[str, JSON]:
    with Image.new("RGB", (64, 64), (value, 0, 0)) as image, io.BytesIO() as out:
        image.save(out, format="PNG")
        body = out.getvalue()
    (root / f"{image_id}.png").write_bytes(body)
    return {
        "id": image_id,
        "path": f"{image_id}.png",
        **experiment.receipt(body),
        "stream": "camera",
        "timestamp_ms": timestamp,
        "sequence_id": sequence,
    }


def manifest(root: Path, *, timed: bool = False, window: bool = False) -> dict[str, JSON]:
    frames: list[JSON] = [
        image_json(root, "a", 40, 100 if timed else None),
        image_json(root, "b", 80, 200 if timed else None),
        image_json(root, "c", 160, 300 if timed else None),
    ]
    source = image_json(root, "query", 120, 500 if timed else None)
    frames.append(source)
    # Byte-identical renamed query source must be excluded as well.
    frames.append(image_json(root, "duplicate", 120, 600 if timed else None))
    return {
        "schema": 1,
        "kind": "frames" if timed else "images",
        "candidates": frames,
        "queries": [
            {
                "id": "q1",
                "image": source,
                "crop": None,
                "cutoffs": {"camera": 450} if timed else None,
                "tracking_window": ["a", "b", "c"] if window else None,
            }
        ],
        "coverage_gaps": [],
    }


def run(
    root: Path,
    doc: dict[str, JSON],
    detector: FakeVision | None = None,
    options: experiment.Options | None = None,
) -> tuple[dict[str, JSON], FakeVision]:
    dataset = experiment.parse_dataset(root, doc, {"synthetic": True})
    expensive = detector or FakeVision()
    report = experiment.Runner(
        dataset, FakeSemantic(), expensive, options or experiment.Options(top_k=2)
    ).run()
    return report, expensive


def ids(value: JSON) -> list[str]:
    return [cast(str, object_value(hit)["id"]) for hit in list_value(value)]


def first_query(report: dict[str, JSON]) -> dict[str, JSON]:
    return object_value(list_value(report["queries"])[0])


@pytest.mark.parametrize(
    ("box", "left", "right"),
    [
        (b"[0.499999999999999999999,0,1,1]", 31, 64),
        (b"[4.99999999999999999999e-1,0,1,1]", 31, 64),
        (b"[5e-1,0e0,1E+0,1.0]", 32, 64),
        (b"[1e-1000,0,1,1]", 0, 64),
        (b"[1e-1000000000000000000000000000000,0,1,1]", 0, 64),
        (b"[0,0,0.500000000000000000001,1]", 0, 33),
        (b"[0,0,1,1]", 0, 64),
    ],
)
def test_exact_manifest_crop_pixels_reach_both_adapters_and_serialized_report(
    tmp_path: Path,
    box: bytes,
    left: int,
    right: int,
) -> None:
    class RecordingSemantic(FakeSemantic):
        def __init__(self) -> None:
            super().__init__()
            self.rasters: list[NDArray[np.uint8]] = []

        def images(self, images: list[Image.Image]) -> list[list[float]]:
            self.rasters.extend(np.array(image, dtype=np.uint8) for image in images)
            return super().images(images)

    class RecordingVision(FakeVision):
        def __init__(self) -> None:
            super().__init__()
            self.rasters: list[NDArray[np.uint8]] = []

        def descriptors(self, images: Sequence[Image.Image]) -> NDArray[np.float32]:
            self.rasters.extend(np.array(image, dtype=np.uint8) for image in images)
            return super().descriptors(images)

    doc = manifest(tmp_path)
    source = object_value(object_value(list_value(doc["queries"])[0])["image"])
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(64, dtype=np.uint8)
    with Image.fromarray(pixels) as image, io.BytesIO() as output:
        image.save(output, format="PNG")
        body = output.getvalue()
    (tmp_path / "query.png").write_bytes(body)
    source.update(experiment.receipt(body))
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical(doc).replace(b'"crop":null', b'"crop":' + box))
    dataset = experiment.load_manifest(path)
    crop = dataset.queries[0].crop
    assert crop is not None and all(isinstance(c, ExactDecimal) for c in crop)
    semantic, detector = RecordingSemantic(), RecordingVision()
    report = experiment.Runner(dataset, semantic, detector, experiment.Options(top_k=2)).run()
    expected = pixels[:, left:right, :]
    np.testing.assert_array_equal(semantic.rasters[-1], expected)
    np.testing.assert_array_equal(detector.rasters[0], expected)
    assert semantic.rasters[-1].shape == (64, right - left, 3)
    destination = tmp_path / "report.json"
    experiment.write_report(destination, report, dataset.verify_images)
    encoded = destination.read_bytes()
    assert b'"crop":' + canonical(list(crop)) in encoded
    restored = first_query(object_value(parse_json(encoded, exact_numbers=True)))["crop"]
    assert isinstance(restored, list) and not any(isinstance(c, str) for c in restored)
    roundtrip_doc = object_value(parse_json(path.read_bytes(), exact_numbers=True))
    object_value(list_value(roundtrip_doc["queries"])[0])["crop"] = restored
    path.write_bytes(canonical(roundtrip_doc))
    assert experiment.load_manifest(path).queries[0].crop == crop


@pytest.mark.parametrize(
    "box",
    [
        b"[-1e-1000,0,1,1]",
        b"[0,-1e-1000,1,1]",
        b"[0,0,1.000000000000000000001,1]",
        b"[0,0,1,1.000000000000000000001]",
    ],
)
def test_manifest_rejects_exact_out_of_range_crop_before_float_rounding(
    tmp_path: Path,
    box: bytes,
) -> None:
    doc = manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical(doc).replace(b'"crop":null', b'"crop":' + box))
    with pytest.raises(ValueError, match="invalid box"):
        experiment.load_manifest(path)


@pytest.mark.parametrize("field", ["schema", "byte_length", "timestamp_ms", "cutoff", "gap"])
@pytest.mark.parametrize("suffix", [".0", "e0"])
def test_exact_crop_parser_preserves_integer_only_manifest_fields(
    tmp_path: Path,
    field: str,
    suffix: str,
) -> None:
    doc = manifest(tmp_path, timed=True)
    target, name = doc, "schema"
    if field in {"byte_length", "timestamp_ms"}:
        target, name = object_value(list_value(doc["candidates"])[0]), field
    elif field == "cutoff":
        target = object_value(object_value(list_value(doc["queries"])[0])["cutoffs"])
        name = "camera"
    elif field == "gap":
        target = {"stream": "camera", "start_ms": 50, "end_ms": 100}
        doc["coverage_gaps"] = [target]
        name = "start_ms"
    token = str(target[name]).encode("ascii") + suffix.encode("ascii")
    target[name] = "INTEGER_TOKEN"
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical(doc).replace(b'"INTEGER_TOKEN"', token))
    with pytest.raises(ValueError):
        experiment.load_manifest(path)


def test_full_ranking_exact_shortlist_rerank_tail_and_shared_caches(tmp_path: Path) -> None:
    doc = manifest(tmp_path)
    queries = list_value(doc["queries"])
    queries.append({**object_value(queries[0]), "id": "q2"})
    report, detector = run(tmp_path, doc)
    query = first_query(report)
    assert ids(query["baseline"]) == ["a", "b", "c"]
    assert query["shortlist"] == ["a", "b"]
    assert ids(query["reranked"]) == ["b", "a", "c"]
    assert object_value(list_value(query["reranked"])[2])["evidence"] == "semantic_tail"
    assert object_value(query["source_exclusion"])["excluded_ids"] == ["query", "duplicate"]
    assert detector.detected == [40, 80]
    assert object_value(report["work"])["semantic_images"] == 7
    assert object_value(report["work"])["descriptor_rows"] == 4
    assert object_value(report["work"])["proposal_cache_hits"] == 2
    assert report["semantic_space"] != report["descriptor_space"]
    assert object_value(query["history"])["detector_temporal_coverage"] == "unknown"
    assert all(object_value(i)["timestamp_ms"] is None for i in list_value(report["inputs"]))


def test_empty_detector_frame_has_explicit_fallback_never_observation(tmp_path: Path) -> None:
    detector = FakeVision()
    detector.empty_colors.add(80)
    report, _ = run(tmp_path, manifest(tmp_path), detector)
    hit = object_value(list_value(first_query(report)["reranked"])[0])
    assert hit["evidence"] == "full_frame_fallback"
    assert hit["proposal_ordinal"] is None
    assert (
        object_value(object_value(report["proposal_evidence"])["b"])["full_image_fallback"] is True
    )


def support(history: JSON) -> list[list[str]]:
    return [
        [
            cast(str, object_value(o)["frame_id"])
            for o in list_value(object_value(t)["observations"])
        ]
        for t in list_value(object_value(history)["tracklets"])
    ]


def test_sparse_shortlist_is_singletons_not_observed_tracking(tmp_path: Path) -> None:
    doc = manifest(tmp_path, timed=True)
    report, detector = run(tmp_path, doc)
    assert detector.detected == [40, 80]
    query = first_query(report)
    assert all(len(chain) == 1 for chain in support(query["history"]))
    assert "singletons" in cast(str, object_value(query["history"])["status"])


def test_window_observes_empty_frames_and_cutoff_before_inference(tmp_path: Path) -> None:
    doc = manifest(tmp_path, timed=True, window=True)
    q = object_value(list_value(doc["queries"])[0])
    q["tracking_window"] = ["a", "b", "c", "query", "duplicate"]
    q["cutoffs"] = {"camera": 250}
    detector = FakeVision()
    detector.empty_colors.add(40)
    report, detector = run(tmp_path, doc, detector)
    assert detector.detected == [40, 80]
    history = object_value(first_query(report)["history"])
    assert history["observed_frame_ids"] == ["a", "b"]
    assert support(history) == [["b"]]
    assert object_value(list_value(history["unknown_gaps"])[0])["reason"] == "no_proposals"


def test_adjacent_proposals_associate_but_episode_and_gap_break_chains(tmp_path: Path) -> None:
    doc = manifest(tmp_path, timed=True, window=True)
    images = list_value(doc["candidates"])
    # Same appearance, distinct PNG content identity via source color; fake DINO agrees.
    images[0] = image_json(tmp_path, "a", 80, 100)
    images[1] = image_json(tmp_path, "b", 160, 200)
    images[2] = image_json(tmp_path, "c", 200, 300)
    report, _ = run(tmp_path, doc)
    assert support(first_query(report)["history"]) == [["a", "b", "c"]]
    object_value(images[2])["sequence_id"] = "episode2"
    report, _ = run(tmp_path, doc)
    assert support(first_query(report)["history"]) == [["a", "b"]]
    doc["coverage_gaps"] = [{"stream": "camera", "start_ms": 100, "end_ms": 200}]
    report, _ = run(tmp_path, doc)
    assert support(first_query(report)["history"]) == [["a"], ["b"]]


@pytest.mark.parametrize(
    "case",
    [
        "schema",
        "no-time",
        "duplicate-id",
        "time-order",
        "cutoff",
        "gap",
        "sparse-window",
        "unknown-time",
        "query-id",
    ],
)
def test_manifest_rejects_ambiguous_temporal_or_identity_inputs(tmp_path: Path, case: str) -> None:
    doc = manifest(tmp_path, timed=True, window=True)
    candidates = list_value(doc["candidates"])
    q = object_value(list_value(doc["queries"])[0])
    if case == "schema":
        doc["schema"] = True
    elif case == "no-time":
        del object_value(candidates[0])["timestamp_ms"]
    elif case == "duplicate-id":
        candidates.append(candidates[0])
    elif case == "time-order":
        object_value(candidates[1])["timestamp_ms"] = 100
    elif case == "cutoff":
        q["cutoffs"] = {}
    elif case == "gap":
        doc["coverage_gaps"] = [{"stream": "camera", "start_ms": 50, "end_ms": 250}]
    elif case == "sparse-window":
        q["tracking_window"] = ["a", "c"]
    elif case == "unknown-time":
        object_value(candidates[0])["timestamp_ms"] = None
    else:
        q["image"] = {**object_value(q["image"]), "sha256": "0" * 64}
    with pytest.raises(ValueError):
        experiment.parse_dataset(tmp_path, doc, {})


def test_window_64_limit_and_budget_exhaustion(tmp_path: Path) -> None:
    doc = manifest(tmp_path, timed=True)
    template = object_value(list_value(doc["candidates"])[0])
    doc["candidates"] = [{**template, "id": f"f{i}", "timestamp_ms": i} for i in range(65)]
    object_value(list_value(doc["queries"])[0])["tracking_window"] = [f"f{i}" for i in range(65)]
    with pytest.raises(ValueError, match="<=64"):
        experiment.parse_dataset(tmp_path, doc, {})
    with pytest.raises(ValueError, match="frame budget"):
        run(
            tmp_path, manifest(tmp_path), options=experiment.Options(top_k=2, max_detector_frames=1)
        )
    dataset = experiment.parse_dataset(tmp_path, manifest(tmp_path), {})
    runner = experiment.Runner(dataset, FakeSemantic(), FakeVision(), experiment.Options())
    runner.started -= 4000
    with pytest.raises(ValueError, match="wall-clock"):
        runner.run()


def test_verified_reads_recheck_tamper_and_reject_symlinks(tmp_path: Path) -> None:
    doc = manifest(tmp_path)
    dataset = experiment.parse_dataset(tmp_path, doc, {})
    image = dataset.images[0]
    (tmp_path / image.path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="image bytes"):
        experiment.load_image(tmp_path, image)
    other = dataset.images[1]
    link = tmp_path / "link.png"
    link.symlink_to(tmp_path / other.path)
    with pytest.raises(OSError):
        experiment.verified_bytes(tmp_path, replace(other, path=link.name))
    doc_path = tmp_path / "manifest.json"
    doc_path.write_bytes(canonical(doc))
    assert experiment.load_manifest(doc_path).identity["manifest"] == experiment.receipt(
        canonical(doc)
    )
    with pytest.raises(ValueError):
        experiment.external(Path("relative.json"), file=True)


def test_pixel_bound_checked_before_decode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = image_json(tmp_path, "large", 40)
    item = experiment.image_input(image, "images")
    monkeypatch.setattr(vision, "MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="raster"):
        experiment.load_image(tmp_path, item)


def test_exclusive_report_prepublication_recheck(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    checks: list[bool] = []
    experiment.write_report(output, {"schema": experiment.SCHEMA}, lambda: checks.append(True))
    assert checks == [True]
    body = output.read_bytes()
    with pytest.raises(FileExistsError):
        experiment.write_report(output, {"schema": experiment.SCHEMA}, lambda: None)
    assert output.read_bytes() == body

    def changed() -> None:
        raise ValueError("source changed")

    failed = tmp_path / "failed.json"
    with pytest.raises(ValueError, match="source changed"):
        experiment.write_report(failed, {}, changed)
    assert not failed.exists()
    symlink = tmp_path / "link.json"
    symlink.symlink_to(output)
    with pytest.raises(FileExistsError):
        experiment.write_report(symlink, {}, lambda: None)


def test_metrics_drop_unknown_only_after_ranking_and_use_original_unknown_at_k() -> None:
    values = experiment.class_metrics(
        ["u", "n", "p", "p2"], {"u": None, "n": False, "p": True, "p2": True}, 2
    )
    assert values == {
        "AP": (0.5 + 2 / 3) / 2,
        "Hit@K": 1,
        "Recall@K": 0.5,
        "unknown@K": 1,
        "judged_candidates": 3,
        "positive_candidates": 2,
        "negative_candidates": 1,
        "primary_eligible": True,
    }
    assert experiment.class_metrics(["n"], {"n": False}, 1)["AP"] is None
    with pytest.raises(ValueError):
        experiment.class_metrics(["n"], {"n": "positive"}, 1)


def test_public_adapter_query_boxes_only_and_postranking_gt_join(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = manifest(tmp_path)
    images = [experiment.image_input(row, "images") for row in list_value(doc["candidates"])]
    items = [Item(i.id, i.path, i.sha256, i.byte_length) for i in images]
    (tmp_path / "manifest.json").write_bytes(canonical({"items": [i.json() for i in items]}))
    for name in ("acquisition.json", "selection.json", "attribution.json"):
        (tmp_path / name).write_bytes(b"{}")
    (tmp_path / "metadata").mkdir()
    for name in METADATA:
        (tmp_path / "metadata" / name).write_bytes(b"synthetic")
    classes: dict[str, JSON] = {}
    for _, mid in CLASS_PROFILE:
        classes[mid] = {
            "boxes": {"query": [{"box": [0.0, 0.0, 1.0, 1.0]}]},
            "judgments": {"a": False, "b": True, "c": None, "query": True},
        }
    truth = tmp_path / "ground-truth.json"
    truth.write_bytes(canonical({"classes": classes}))
    monkeypatch.setattr(
        experiment, "verified_acquisition", lambda root: ({"verified": True}, {}, items)
    )
    dataset, query_classes = experiment.openimages_dataset(tmp_path, 6)
    # Each class uses the benchmark's own first boxed positive; shared sources are permitted.
    assert [q.id for q in dataset.queries] == [mid + ":image" for _, mid in CLASS_PROFILE[:6]]
    assert dataset.identity["content_alias_count"] == 1
    assert len(dataset.images) == 4
    assert dataset.queries[0].crop is not None
    assert all(isinstance(c, ExactDecimal) for c in dataset.queries[0].crop)
    assert not any("boxes" in image.public() for image in dataset.images)
    report = experiment.Runner(
        dataset, FakeSemantic(), FakeVision(), experiment.Options(top_k=2)
    ).run()
    before = canonical(report["queries"])
    experiment.join_openimages_metrics(report, tmp_path, query_classes, 2)
    assert canonical(report["queries"]) != before
    query = first_query(report)
    assert ids(query["reranked"]) == ["b", "a", "c"]
    assert object_value(query["source_exclusion"])["source_alias_ids"] == ["duplicate", "query"]
    signature = object_value(query["query_signature"])
    assert signature["class"] == CLASS_PROFILE[0][1]
    assert signature["source_id"] == "query"
    assert query["query_signature_sha256"] == fingerprint(signature)
    assert object_value(object_value(report["class_metrics"])["mAP"])["reranked"] == 1.0
    # Candidate GT boxes cannot affect blind output, even if they would favor the wrong image.
    object_value(classes[CLASS_PROFILE[0][1]])["boxes"] = {
        "query": [{"box": [0.0, 0.0, 1.0, 1.0]}],
        "a": [{"box": [0.2, 0.2, 0.4, 0.4]}],
    }
    truth.write_bytes(canonical({"classes": classes}))
    reloaded, _ = experiment.openimages_dataset(tmp_path, 6)
    blind_again = experiment.Runner(
        reloaded, FakeSemantic(), FakeVision(), experiment.Options(top_k=2)
    ).run()
    assert ids(first_query(blind_again)["reranked"]) == ["b", "a", "c"]


def test_cli_complete_flow_fake_expensive_adapters_real_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = manifest(tmp_path)
    source = tmp_path / "manifest.json"
    source.write_bytes(canonical(doc))
    model, vision_root = tmp_path / "model", tmp_path / "vision"
    model.mkdir()
    vision_root.mkdir()
    output = tmp_path / "result.json"
    monkeypatch.setattr(experiment, "verify_model", lambda root: {"model": "synthetic"})
    monkeypatch.setattr(experiment, "checkpoint_for_manifest", lambda manifest: DEFAULT_CHECKPOINT)
    monkeypatch.setattr(vision, "verify_models", lambda root: {"vision": "synthetic"})
    monkeypatch.setattr(vision, "VisionModels", lambda *args, **kwargs: FakeVision())
    monkeypatch.setattr(experiment, "SemanticModel", lambda *args, **kwargs: FakeSemantic())
    arguments = [
        "manifest",
        "--model-dir",
        str(model),
        "--vision-root",
        str(vision_root),
        "--manifest",
        str(source),
        "--output",
        str(output),
        "--top-k",
        "2",
    ]
    experiment.main(arguments)
    report = object_value(parse_json(output.read_bytes()))
    assert report["schema"] == experiment.SCHEMA
    assert ids(first_query(report)["reranked"]) == ["b", "a", "c"]
    with pytest.raises(SystemExit, match="failed validation"):
        experiment.main(arguments)


def test_verifier_rejects_aggregate_substitution_and_threshold_rounding() -> None:
    summary = {
        "num_statements": 100,
        "covered_lines": 95,
        "num_branches": 20,
        "covered_branches": 5,
    }
    report: dict[str, object] = {"files": {verifier.CORE: {"summary": summary}}}
    assert verifier.coverage_counts(report) == (100, 95, 20, 5)
    summary["covered_lines"] = 94
    with pytest.raises(ValueError, match="95%"):
        verifier.coverage_counts(report)
    with pytest.raises(ValueError):
        verifier.coverage_counts({"files": {"aggregate": {"summary": summary}}})
    with pytest.raises(ValueError):
        verifier.coverage_counts(
            {"files": {verifier.CORE: {"summary": {**summary, "covered_lines": True}}}}
        )


def test_100_images_six_queries_20_proposals_bounded_shared_cache(tmp_path: Path) -> None:
    class ManyProposals(FakeVision):
        def proposals(self, image: Image.Image) -> tuple[vision.Proposal, ...]:
            proposal = super().proposals(image)[0]
            self.last_proposal_counts = vision.ProposalCounts(100, 80, 0, 0, 0, 20)
            return tuple(replace(proposal, query_index=i) for i in range(20))

    doc = manifest(tmp_path)
    doc["candidates"] = [image_json(tmp_path, f"f{i:03}", i + 1) for i in range(100)]
    query = object_value(list_value(doc["queries"])[0])
    doc["queries"] = [{**query, "id": f"q{i}"} for i in range(6)]
    report, detector = run(tmp_path, doc, ManyProposals(), experiment.Options())
    assert len(detector.detected) == 20
    work = object_value(report["work"])
    assert work["semantic_images"] == 106
    assert work["descriptor_rows"] == 406
    assert work["descriptor_batches"] == 206
    assert work["proposal_cache_hits"] == 100
    assert object_value(report["cache"])["descriptor_elements"] == 20 * 20 * 384
    assert all(
        len(list_value(object_value(q)["baseline"])) == 100 for q in list_value(report["queries"])
    )


@pytest.mark.parametrize("changed", ["source", "model", "input"])
def test_cli_rejects_late_identity_change_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    doc = manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(canonical(doc))
    model, vision_root = tmp_path / "model", tmp_path / "vision"
    model.mkdir()
    vision_root.mkdir()
    output = tmp_path / "result.json"
    calls = 0

    def identity(root: Path | None = None) -> dict[str, JSON]:
        nonlocal calls
        calls += 1
        return {"identity": "before" if calls == 1 else "after"}

    class ChangedInput(FakeSemantic):
        def images(self, images: list[Image.Image]) -> list[list[float]]:
            result = super().images(images)
            if len(self.batches) == 4:
                (tmp_path / "query.png").write_bytes(b"late changed image bytes")
            return result

    monkeypatch.setattr(experiment, "verify_model", lambda root: {"model": "synthetic"})
    monkeypatch.setattr(experiment, "checkpoint_for_manifest", lambda manifest: DEFAULT_CHECKPOINT)
    monkeypatch.setattr(vision, "verify_models", lambda root: {"vision": "synthetic"})
    monkeypatch.setattr(vision, "VisionModels", lambda *args, **kwargs: FakeVision())
    monkeypatch.setattr(experiment, "SemanticModel", lambda *args, **kwargs: FakeSemantic())
    if changed == "input":
        monkeypatch.setattr(experiment, "SemanticModel", lambda *args, **kwargs: ChangedInput())
    else:
        monkeypatch.setattr(
            experiment, "source_identity" if changed == "source" else "verify_model", identity
        )
    with pytest.raises(SystemExit, match="failed validation"):
        experiment.main(
            [
                "manifest",
                "--model-dir",
                str(model),
                "--vision-root",
                str(vision_root),
                "--manifest",
                str(manifest_path),
                "--output",
                str(output),
                "--top-k",
                "2",
            ]
        )
    assert not output.exists()


def test_source_hash_reader_rejects_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_bytes(b"# synthetic source\n")
    assert experiment.source_bytes(source) == b"# synthetic source\n"
    alias = tmp_path / "alias.py"
    alias.symlink_to(source)
    with pytest.raises(OSError):
        experiment.source_bytes(alias)


class SyntheticSiglip:
    """Tiny genuine Torch feature computation behind the expensive pretrained loader boundary."""

    def __init__(self) -> None:
        self.config = SimpleNamespace(
            vision_config=SimpleNamespace(image_size=224, patch_size=16, hidden_size=768),
            text_config=SimpleNamespace(max_position_embeddings=64),
            _attn_implementation="eager",
        )
        self.training = True
        self.dtype = torch.float32
        self.device = torch.device("cpu")

    def parameters(self) -> tuple[SimpleNamespace]:
        return (SimpleNamespace(numel=lambda: DEFAULT_CHECKPOINT.parameter_count),)

    def to(self, *, device: str, dtype: torch.dtype) -> Self:
        self.device, self.dtype = torch.device(device), dtype
        return self

    def eval(self) -> Self:
        self.training = False
        return self

    def get_image_features(self, *, pixel_values: torch.Tensor) -> torch.Tensor:
        assert not torch.is_grad_enabled()
        assert pixel_values.dtype == torch.float32
        assert tuple(pixel_values.shape[1:]) == (3, 224, 224)
        return torch.nn.functional.pad(pixel_values.mean(dim=(2, 3)), (0, 765))


@dataclass
class SemanticInstallation:
    source: Path
    package: Path
    runtime: Path
    models: Path

    def runtime_file(self, name: str, body: bytes) -> None:
        content = self.runtime / (name + ".py")
        metadata = self.runtime / (name + ".dist-info")
        metadata.mkdir(exist_ok=True)
        content.write_bytes(body)
        (metadata / "METADATA").write_text(f"Name: {name}\nVersion: 1.0.synthetic\n")
        digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
        (metadata / "RECORD").write_text(
            f"{name}.py,sha256={digest},{len(body)}\n{name}.dist-info/RECORD,,\n"
        )


@pytest.fixture
def semantic_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SemanticInstallation]:
    from threadpoolctl import threadpool_limits
    from transformers import SiglipModel

    source, package, runtime, models = (
        tmp_path / "runner.py",
        tmp_path / "helpers",
        tmp_path / "runtime",
        tmp_path / "models",
    )
    source.write_bytes(b"# synthetic runner source v1\n")
    for root in (package, runtime, models):
        root.mkdir()
    (package / "images.py").write_bytes(b"# synthetic packaged preprocessing v1\n")
    installation = SemanticInstallation(source, package, runtime, models)
    for name in experiment.SEMANTIC_DISTRIBUTIONS:
        installation.runtime_file(name, f"# synthetic {name} runtime v1\n".encode())
    original_distribution = importlib.metadata.distribution

    def distribution(name: str) -> importlib.metadata.Distribution:
        if name in experiment.SEMANTIC_DISTRIBUTIONS:
            return importlib.metadata.PathDistribution(installation.runtime / (name + ".dist-info"))
        return original_distribution(name)

    def pretrained(root: str, **options: object) -> tuple[SyntheticSiglip, dict[str, JSON]]:
        assert options["local_files_only"] is True
        assert options["trust_remote_code"] is False
        assert options["use_safetensors"] is True
        assert options["dtype"] == torch.float32
        assert options["attn_implementation"] == "eager"
        return SyntheticSiglip(), {
            name: []
            for name in (
                "missing_keys",
                "unexpected_keys",
                "mismatched_keys",
                "error_msgs",
            )
        }

    monkeypatch.setattr(experiment, "__file__", str(source))
    monkeypatch.setattr(
        experiment,
        "implementation_files",
        lambda: runtime_identity.implementation_files(installation.package),
    )
    monkeypatch.setattr(importlib.metadata, "distribution", distribution)
    monkeypatch.setattr(SiglipModel, "from_pretrained", pretrained)
    monkeypatch.setattr(
        experiment,
        "verify_model",
        lambda root: {
            "artifact_sha256": "1" * 64,
            "parameter_count": DEFAULT_CHECKPOINT.parameter_count,
        },
    )
    monkeypatch.setattr(experiment, "checkpoint_for_manifest", lambda manifest: DEFAULT_CHECKPOINT)
    previous_threads = torch.get_num_threads()
    previous_deterministic = torch.are_deterministic_algorithms_enabled()
    previous_warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    previous_precision = torch.get_float32_matmul_precision()
    torch.set_num_threads(4)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    try:
        with threadpool_limits(limits=4):
            yield installation
    finally:
        torch.set_num_threads(previous_threads)
        torch.use_deterministic_algorithms(previous_deterministic, warn_only=previous_warn_only)
        torch.set_float32_matmul_precision(previous_precision)


def test_semantic_identity_binds_real_runtime_helpers_and_tiny_image_computation(
    semantic_installation: SemanticInstallation,
) -> None:
    model = experiment.SemanticModel(semantic_installation.models, batch_size=2)
    identity = model.identity
    assert model.model_fingerprint == fingerprint(identity)
    assert identity["version"] == "object-experiment-siglip2-base224-image-only-v2"
    runtime = object_value(identity["numerical_runtime"])
    assert runtime["version"] == "numerical-runtime-v2"
    distributions = object_value(runtime["distributions"])
    assert set(distributions) == set(experiment.SEMANTIC_DISTRIBUTIONS)
    assert object_value(distributions["torch"])["file_count"] == 1
    settings = object_value(identity["effective_runtime_settings"])
    assert settings["threads"] == 4 and settings["interop_threads"] == 1
    assert "threadpools" in settings
    implementation = object_value(identity["implementation"])
    assert set(object_value(implementation["packaged_implementation_files"])) == {"images.py"}
    with Image.new("RGB", (64, 64), (10, 30, 50)) as image:
        vectors = np.asarray(model.images([image]), dtype=np.float32)
    assert vectors.shape == (1, 768)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), [1.0], atol=1e-6)
    identity["version"] = "mutated external copy"
    assert model.identity["version"] != identity["version"]


@pytest.mark.parametrize("component", ["runner", "packaged"])
def test_semantic_source_change_invalidates_loaded_identity_and_changes_new_fingerprint(
    semantic_installation: SemanticInstallation,
    component: str,
) -> None:
    model = experiment.SemanticModel(semantic_installation.models, batch_size=2)
    before = model.model_fingerprint
    path = (
        semantic_installation.source
        if component == "runner"
        else semantic_installation.package / "images.py"
    )
    path.write_bytes(b"# changed synthetic computation source\n")
    with pytest.raises(ValueError, match="implementation changed"):
        _ = model.identity
    with (
        Image.new("RGB", (64, 64)) as image,
        pytest.raises(ValueError, match="implementation changed"),
    ):
        model.images([image])
    assert experiment.SemanticModel(semantic_installation.models, 2).model_fingerprint != before


def test_semantic_same_version_runtime_content_is_bound_and_record_tamper_rejected(
    semantic_installation: SemanticInstallation,
) -> None:
    before = experiment.SemanticModel(semantic_installation.models, 2)
    semantic_installation.runtime_file("torch", b"# different runtime code, same version\n")
    after = experiment.SemanticModel(semantic_installation.models, 2)
    assert before.model_fingerprint != after.model_fingerprint
    for model in (before, after):
        runtime = object_value(model.identity["numerical_runtime"])
        assert (
            object_value(object_value(runtime["distributions"])["torch"])["version"]
            == "1.0.synthetic"
        )
    (semantic_installation.runtime / "torch.py").write_bytes(b"# undeclared runtime tamper\n")
    with pytest.raises(ValueError, match="RECORD"):
        experiment.SemanticModel(semantic_installation.models, 2)


@pytest.mark.parametrize("setting", ["batch", "threads", "matmul", "preprocessing", "epsilon"])
def test_semantic_effective_settings_change_invalidates_loaded_fingerprint(
    semantic_installation: SemanticInstallation,
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
) -> None:
    model = experiment.SemanticModel(semantic_installation.models, 2)
    before = model.model_fingerprint
    threads, batch_size = 4, 2
    if setting == "batch":
        model.batch_size = batch_size = 1
    elif setting == "threads":
        torch.set_num_threads(threads := 2)
    elif setting == "matmul":
        torch.set_float32_matmul_precision(
            "high" if torch.get_float32_matmul_precision() == "highest" else "highest"
        )
    elif setting == "preprocessing":
        monkeypatch.setattr(experiment, "SEMANTIC_PIXEL_DIVISOR", 128.0)
    else:
        monkeypatch.setattr(experiment, "SEMANTIC_NORM_EPS", 1e-10)
    with pytest.raises(ValueError, match="changed after load"):
        _ = model.model_fingerprint
    changed = experiment.SemanticModel(semantic_installation.models, batch_size, threads)
    assert changed.model_fingerprint != before


@pytest.mark.parametrize("setting", ["training", "dtype", "attention"])
def test_semantic_model_execution_mode_mutations_rejected(
    semantic_installation: SemanticInstallation,
    setting: str,
) -> None:
    model = experiment.SemanticModel(semantic_installation.models, 2)
    if setting == "training":
        model.model.training = True
    elif setting == "dtype":
        model.model.dtype = torch.float64
    else:
        model.model.config._attn_implementation = "sdpa"
    with pytest.raises(ValueError, match="precision/device/eval"):
        _ = model.identity


def test_semantic_path_relocation_preserves_content_identity(
    semantic_installation: SemanticInstallation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = experiment.SemanticModel(semantic_installation.models, 2)
    identity, digest = before.identity, before.model_fingerprint
    for attribute in ("source", "package", "runtime", "models"):
        path = cast(Path, getattr(semantic_installation, attribute))
        relocated = tmp_path / ("relocated-" + path.name)
        path.rename(relocated)
        setattr(semantic_installation, attribute, relocated)
    monkeypatch.setattr(experiment, "__file__", str(semantic_installation.source))
    os.utime(semantic_installation.source, (100, 100))
    after = experiment.SemanticModel(semantic_installation.models, 2)
    assert after.model_fingerprint == digest
    assert after.identity == identity
    assert str(tmp_path).encode() not in canonical(identity)


def test_semantic_source_mutation_during_inference_rejects_descriptor_return(
    semantic_installation: SemanticInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = experiment.SemanticModel(semantic_installation.models, 2)
    original = SyntheticSiglip.get_image_features

    def changed(self: SyntheticSiglip, *, pixel_values: torch.Tensor) -> torch.Tensor:
        result = original(self, pixel_values=pixel_values)
        semantic_installation.source.write_bytes(b"# changed during synthetic inference\n")
        return result

    monkeypatch.setattr(SyntheticSiglip, "get_image_features", changed)
    with Image.new("RGB", (64, 64)) as image:
        with pytest.raises(ValueError, match="implementation changed"):
            model.images([image])


def public_primary_fixture(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[Item], dict[str, JSON]]:
    # Deliberately reversed source order. Scissors has only one positive content;
    # mug has no negative. Primary class order must therefore retain mobile phone.
    rows = [
        image_json(root, name, value)
        for name, value in (
            ("z", 200),
            ("unknown", 160),
            ("positive", 80),
            ("negative", 40),
            ("a", 120),
        )
    ]
    images = [experiment.image_input(row, "images") for row in rows]
    items = [Item(i.id, i.path, i.sha256, i.byte_length) for i in images]
    classes: dict[str, JSON] = {}
    for name, mid in CLASS_PROFILE:
        judgments: dict[str, JSON] = {"a": True, "z": True, "positive": True, "negative": False}
        if name == "Scissors":
            judgments = {"a": True, "negative": False}
        elif name == "Mug":
            judgments = {"a": True, "positive": True}
        classes[mid] = {
            "judgments": judgments,
            "boxes": {
                "z": [{"box": [0, 0, 1, 1]}],
                "a": [{"box": [0, 0, 0.5, 1]}, {"box": [0.5, 0, 1, 1]}],
                "negative": [{"box": [0, 0, 1, 1]}],
            },
        }
    (root / "manifest.json").write_bytes(canonical({"items": [i.json() for i in items]}))
    (root / "ground-truth.json").write_bytes(canonical({"classes": classes}))
    for name in ("acquisition.json", "selection.json", "attribution.json"):
        (root / name).write_bytes(b"{}")
    (root / "metadata").mkdir()
    for name in METADATA:
        (root / "metadata" / name).write_bytes(b"synthetic")
    monkeypatch.setattr(
        experiment, "verified_acquisition", lambda path: ({"verified": True}, {}, items)
    )
    return items, classes


def test_public_primary_cohort_matches_benchmark_source_order_and_stable_box_ties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_primary_fixture(tmp_path, monkeypatch)
    dataset, query_classes = experiment.openimages_dataset(tmp_path, 6)
    expected_mids = [mid for name, mid in CLASS_PROFILE if name not in {"Scissors", "Mug"}]
    assert list(query_classes.values()) == expected_mids
    assert len(dataset.queries) == 6
    assert all(q.image.id == "a" for q in dataset.queries)
    assert all(canonical(list(q.crop or ())) == b"[0,0,0.5,1]" for q in dataset.queries)
    report = experiment.Runner(dataset, FakeSemantic(), FakeVision(), experiment.Options()).run()
    experiment.join_openimages_metrics(report, tmp_path, query_classes, 20)
    metrics = object_value(report["class_metrics"])
    assert metrics["eligible_queries"] == {"baseline": 6, "reranked": 6}
    assert metrics["excluded_queries"] == {"baseline": [], "reranked": []}
    assert all(
        object_value(object_value(q)["query_signature"])["source_id"] == "a"
        for q in list_value(report["queries"])
    )


def test_first_frozen_primary_crop_cannot_be_replaced_with_supported_later_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, classes = public_primary_fixture(tmp_path, monkeypatch)
    boxes = object_value(object_value(classes[CLASS_PROFILE[0][1]])["boxes"])
    boxes["a"] = [{"box": [0, 0, 0.1, 0.1]}]
    (tmp_path / "ground-truth.json").write_bytes(canonical({"classes": classes}))
    with pytest.raises(experiment.UnsupportedQuery, match="no alternate selected"):
        experiment.openimages_dataset(tmp_path, 6)


def test_content_aliases_do_not_inflate_primary_eligibility_or_metric_weight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items, classes = public_primary_fixture(tmp_path, monkeypatch)
    source = next(i for i in items if i.id == "a")
    alias = replace(source, id="alias")
    items.append(alias)
    positive = next(i for i in items if i.id == "positive")
    items.append(replace(positive, id="positive-copy"))
    scissors = object_value(classes[dict(CLASS_PROFILE)["Scissors"]])
    object_value(scissors["judgments"])["alias"] = True
    # Unknown alias evidence merges to known positive content, but never to another vote.
    (tmp_path / "ground-truth.json").write_bytes(canonical({"classes": classes}))
    dataset, query_classes = experiment.openimages_dataset(tmp_path, 6)
    assert dict(CLASS_PROFILE)["Scissors"] not in query_classes.values()
    assert dataset.identity["source_asset_count"] == 7
    assert dataset.identity["unique_content_count"] == 5
    assert dataset.identity["content_alias_count"] == 2
    report = experiment.Runner(dataset, FakeSemantic(), FakeVision(), experiment.Options()).run()
    experiment.join_openimages_metrics(report, tmp_path, query_classes, 20)
    query = first_query(report)
    assert len(ids(query["baseline"])) == 4
    assert (
        object_value(object_value(query["class_metrics"])["baseline"])["positive_candidates"] == 2
    )
    assert object_value(query["source_exclusion"])["source_alias_ids"] == ["a", "alias"]
    object_value(scissors["judgments"])["alias"] = False
    (tmp_path / "ground-truth.json").write_bytes(canonical({"classes": classes}))
    with pytest.raises(ValueError, match="conflicting judgments"):
        experiment.openimages_dataset(tmp_path, 6)


def test_primary_metric_aggregation_rechecks_both_polarities_and_ignores_duplicate_votes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, classes = public_primary_fixture(tmp_path, monkeypatch)
    dataset, query_classes = experiment.openimages_dataset(tmp_path, 6)
    report = experiment.Runner(dataset, FakeSemantic(), FakeVision(), experiment.Options()).run()
    # Late labels cannot rewrite blind ranks; the primary metric gate still abstains.
    judgments = object_value(object_value(classes[CLASS_PROFILE[0][1]])["judgments"])
    judgments["negative"] = None
    (tmp_path / "ground-truth.json").write_bytes(canonical({"classes": classes}))
    experiment.join_openimages_metrics(report, tmp_path, query_classes, 20)
    metrics = object_value(report["class_metrics"])
    assert metrics["eligible_queries"] == {"baseline": 5, "reranked": 5}
    assert (
        object_value(list_value(object_value(metrics["excluded_queries"])["baseline"])[0])["reason"]
        == "no_negative"
    )
    assert (
        experiment.class_metrics(["positive"], {"positive": True}, 20)["primary_eligible"] is False
    )
    with pytest.raises(ValueError, match="duplicate candidate"):
        experiment.class_metrics(["positive", "positive"], {"positive": True}, 20)
