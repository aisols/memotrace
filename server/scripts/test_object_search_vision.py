"""Synthetic vision/artifact regressions: no downloads, datasets or private inputs."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import os
import platform
import socket
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest
import torch
from memotrace_ml import acquire
from memotrace_ml import identity as runtime_identity
from memotrace_ml.common import JSON, canonical, fingerprint, object_value
from PIL import Image

from scripts import object_search_vision as vision


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("network is forbidden in synthetic vision tests")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@dataclass
class Artifacts:
    root: Path
    bodies: dict[str, bytes]
    fetched: list[str]


@pytest.fixture
def artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Artifacts:
    bodies: dict[str, bytes] = {}
    checkpoints: list[vision._Checkpoint] = []
    for checkpoint in vision._CHECKPOINTS:
        pins: list[vision._Artifact] = []
        for artifact in checkpoint.files:
            body = f"synthetic {checkpoint.model_id} {artifact.name}".encode()
            digest = (
                hashlib.sha256(body).hexdigest()
                if artifact.kind == "sha256"
                else hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
            )
            pinned = replace(artifact, byte_length=len(body), digest=digest)
            pins.append(pinned)
            bodies[vision._url(checkpoint, pinned)] = body
        checkpoints.append(replace(checkpoint, files=tuple(pins)))
    monkeypatch.setattr(vision, "_CHECKPOINTS", tuple(checkpoints))
    result = Artifacts(tmp_path / "models", bodies, [])

    def fetch(url: str, fd: int, max_bytes: int, seconds: float) -> dict[str, JSON]:
        result.fetched.append(url)
        body = result.bodies[url]
        assert len(body) <= max_bytes
        assert seconds == 1800
        os.write(fd, body)
        return {"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}

    monkeypatch.setattr(acquire, "bounded_fetch", fetch)
    return result


def test_independent_pins_and_fixed_inventory() -> None:
    detector, descriptor = vision._CHECKPOINTS
    assert (detector.model_id, detector.revision) == (
        "hustvl/yolos-tiny",
        "95a90f3c189fbfca3bcfc6d7315b9e84d95dc2de",
    )
    assert (descriptor.model_id, descriptor.revision) == (
        "facebook/dinov2-small",
        "ed25f3a31f01632728cabb09d1542f84ab7b0056",
    )
    expected = (
        (
            (
                25978888,
                "sha256",
                "5a6a017a20cb522dd347271fa5bd670467e456176aaccd940090e50985ac6e74",
            ),
            (4133, "git_blob_sha1", "9b1dc5fbaca6c50cb8a92488448be33bf7a60260"),
            (291, "git_blob_sha1", "79bb34ebb0f2c7ba7a8f0a3d99148a2cfb61019c"),
            (4618, "git_blob_sha1", "e96ad2f972e86d4a7d46005fdc3410f15defdc14"),
        ),
        (
            (
                88249960,
                "sha256",
                "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1",
            ),
            (547, "git_blob_sha1", "5664b325e6258d3960fad8c4c1cff958f3cc2272"),
            (436, "git_blob_sha1", "ff5b47c2edcd1d3556d63c01a65d93b58b9efce1"),
            (3033, "git_blob_sha1", "6b3380957df44ed203ec1d5102e1245accbbbba9"),
        ),
    )
    for checkpoint, pins in zip(vision._CHECKPOINTS, expected, strict=True):
        assert tuple(artifact.name for artifact in checkpoint.files) == (
            "model.safetensors",
            "config.json",
            "preprocessor_config.json",
            "README.md",
        )
        assert tuple((pin.byte_length, pin.kind, pin.digest) for pin in checkpoint.files) == pins


def test_git_blob_sha1_is_not_raw_sha1_or_sha256() -> None:
    body = b"synthetic config\n"
    digest = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
    artifact = vision._Artifact("config.json", len(body), "git_blob_sha1", digest)
    vision._validate_blob(artifact, body)
    for invalid in (
        replace(artifact, digest=hashlib.sha1(body).hexdigest()),
        replace(artifact, digest=hashlib.sha256(body).hexdigest()),
        replace(artifact, byte_length=len(body) + 1),
        replace(artifact, kind="sha256"),
    ):
        with pytest.raises(ValueError):
            vision._validate_blob(invalid, body)


def test_acquire_verify_receipts_and_network_free_resume(artifacts: Artifacts) -> None:
    identity = vision.acquire_models(artifacts.root)
    assert len(artifacts.fetched) == 8
    assert vision.verify_models(artifacts.root) == identity
    assert vision.acquire_models(artifacts.root) == identity
    assert len(artifacts.fetched) == 8
    assert str(artifacts.root).encode() not in canonical(identity)
    for checkpoint in vision._CHECKPOINTS:
        root = artifacts.root / checkpoint.directory
        assert set(path.name for path in root.iterdir()) == {
            "model.safetensors",
            "config.json",
            "preprocessor_config.json",
            "README.md",
            "manifest.json",
        }
        manifest = vision._manifest(root, checkpoint)
        assert manifest["license"] == "Apache-2.0"
        for artifact in checkpoint.files:
            receipt = vision._receipt(root, checkpoint, artifact)
            body = artifacts.bodies[vision._url(checkpoint, artifact)]
            assert receipt["sha256"] == hashlib.sha256(body).hexdigest()
            assert receipt["byte_length"] == len(body)
            assert receipt["pin"] == {"kind": artifact.kind, "digest": artifact.digest}


def test_bad_git_blob_is_rejected_before_publication_then_resumes(artifacts: Artifacts) -> None:
    checkpoint = vision._CHECKPOINTS[0]
    artifact = checkpoint.files[1]
    url = vision._url(checkpoint, artifact)
    good = artifacts.bodies[url]
    artifacts.bodies[url] = b"x" * len(good)
    with pytest.raises(ValueError, match="Git blob SHA-1"):
        vision.acquire_models(artifacts.root)
    root = artifacts.root / checkpoint.directory
    assert {path.name for path in root.iterdir()} == {"model.safetensors"}
    with pytest.raises(ValueError):
        vision.verify_models(artifacts.root)
    artifacts.bodies[url] = good
    vision.acquire_models(artifacts.root)
    assert len(artifacts.fetched) == 9  # 8 files + one rejected config; weights retained.


def test_bad_safetensors_is_rejected_before_publication(artifacts: Artifacts) -> None:
    checkpoint = vision._CHECKPOINTS[0]
    url = vision._url(checkpoint, checkpoint.files[0])
    artifacts.bodies[url] = b"x" * len(artifacts.bodies[url])
    with pytest.raises(ValueError, match="digest"):
        vision.acquire_models(artifacts.root)
    assert list((artifacts.root / checkpoint.directory).iterdir()) == []


@pytest.mark.parametrize("filename", ["config.json", "model.safetensors", "manifest.json"])
def test_tampered_artifacts_and_manifests_fail_without_fetch(
    artifacts: Artifacts, filename: str
) -> None:
    vision.acquire_models(artifacts.root)
    path = artifacts.root / "dinov2-small" / filename
    original = path.read_bytes()
    path.write_bytes(b"x" + original[1:])
    for operation in (vision.verify_models, vision.acquire_models):
        with pytest.raises(ValueError):
            operation(artifacts.root)
    assert len(artifacts.fetched) == 8
    assert path.read_bytes() == b"x" + original[1:]


@pytest.mark.parametrize(
    "filename", ["config.json.partial", ".memotrace-stage-stale", "pytorch_model.bin", "extra.json"]
)
def test_inventory_rejects_partial_stage_bin_and_extra(artifacts: Artifacts, filename: str) -> None:
    vision.acquire_models(artifacts.root)
    (artifacts.root / "yolos-tiny" / filename).write_bytes(b"synthetic")
    for operation in (vision.verify_models, vision.acquire_models):
        with pytest.raises(ValueError, match="inventory"):
            operation(artifacts.root)
    assert len(artifacts.fetched) == 8


def test_incomplete_sealed_root_does_not_redownload(artifacts: Artifacts) -> None:
    vision.acquire_models(artifacts.root)
    (artifacts.root / "dinov2-small" / "config.json").unlink()
    with pytest.raises(ValueError, match="incomplete sealed"):
        vision.acquire_models(artifacts.root)
    assert len(artifacts.fetched) == 8


def test_all_retained_models_preflight_before_any_network(artifacts: Artifacts) -> None:
    vision.acquire_models(artifacts.root)
    detector = artifacts.root / "yolos-tiny"
    (detector / "manifest.json").unlink()
    (detector / "config.json").unlink()
    descriptor = artifacts.root / "dinov2-small"
    (descriptor / "manifest.json").unlink()
    (descriptor / "config.json").write_bytes(b"changed")
    with pytest.raises(ValueError):
        vision.acquire_models(artifacts.root)
    assert len(artifacts.fetched) == 8
    assert not (detector / "config.json").exists()


def test_unsealed_partial_resumes_only_independently_pinned_bytes(artifacts: Artifacts) -> None:
    vision.acquire_models(artifacts.root)
    root = artifacts.root / "yolos-tiny"
    (root / "manifest.json").unlink()
    (root / "preprocessor_config.json").unlink()
    with pytest.raises(ValueError):
        vision.verify_models(artifacts.root)
    vision.acquire_models(artifacts.root)
    assert len(artifacts.fetched) == 9


def test_roots_are_explicit_external_and_verify_is_read_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        vision.verify_models(Path("relative"))
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        vision.verify_models(missing)
    assert not missing.exists()
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="outside Git"):
        vision.acquire_models(tmp_path / "models")
    with pytest.raises(ValueError, match="absolute"):
        vision.verify_models(tmp_path / ".." / "escape")


@pytest.mark.parametrize("level", ["file", "model", "root"])
def test_symlinks_fail_closed(artifacts: Artifacts, level: str) -> None:
    vision.acquire_models(artifacts.root)
    target = artifacts.root / "yolos-tiny" / "config.json"
    if level == "model":
        target = target.parent
    elif level == "root":
        target = artifacts.root
    saved = artifacts.root.parent / "saved"
    target.rename(saved)
    target.symlink_to(saved)
    for operation in (vision.verify_models, vision.acquire_models):
        with pytest.raises((OSError, ValueError)):
            operation(artifacts.root)
    assert len(artifacts.fetched) == 8


def test_extra_root_entry_is_rejected(artifacts: Artifacts) -> None:
    vision.acquire_models(artifacts.root)
    (artifacts.root / "extra").mkdir()
    with pytest.raises(ValueError, match="root inventory"):
        vision.verify_models(artifacts.root)
    with pytest.raises(ValueError, match="root inventory"):
        vision.acquire_models(artifacts.root)


def test_filter_geometry_ties_counts_and_separate_fallback() -> None:
    scores = np.full(100, 0.1, dtype=np.float32)
    classes = np.ones(100, dtype=np.int64)
    boxes = np.full((100, 4), 0.5, dtype=np.float32)
    scores[:25] = 0.9
    scores[0] = 0.95
    boxes[0] = (0.0, 1.0, 0.5, 0.5)  # clip at left and bottom
    classes[1] = 0  # excluded N/A
    boxes[2] = (0.5, 0.5, 0.01, 0.01)
    scores[25] = 0.2  # equality is excluded, not > .20 after Python float conversion
    scores[26] = np.nextafter(np.float32(0.2), np.float32(1))
    boxes[3] = (0.5, 0.5, 0.25, 0.25)
    proposals, counts = vision._filter_proposals(scores, classes, boxes, (101, 79), frozenset({0}))
    assert counts == vision.ProposalCounts(100, 74, 1, 1, 4, 20)
    assert counts.candidates == counts.filtered + counts.truncated + counts.returned
    assert [proposal.query_index for proposal in proposals] == [0, *range(3, 22)]
    assert proposals[0].pixel_box == (0, 59, 26, 79)
    assert proposals[0].box == (0.0, 59 / 79, 26 / 101, 1.0)
    assert proposals[1].pixel_box == (37, 29, 64, 50)
    pixels = np.arange(101 * 79 * 3, dtype=np.uint8).reshape(79, 101, 3)
    image = Image.fromarray(pixels)
    np.testing.assert_array_equal(np.asarray(proposals[0].crop(image)), pixels[59:79, 0:26])
    fallback = vision.full_image_fallback(image)
    assert fallback.box == (0, 0, 1, 1)
    assert fallback.pixel_box == (0, 0, 101, 79)
    assert not hasattr(fallback, "score")
    np.testing.assert_array_equal(np.asarray(fallback.crop(image)), pixels)
    with pytest.raises(ValueError, match="geometry"):
        proposals[0].crop(Image.new("RGB", (102, 79)))


def test_exact_minimum_crop_and_empty_detector_result() -> None:
    scores = np.zeros(100, dtype=np.float32)
    classes = np.ones(100, dtype=np.int64)
    boxes = np.full((100, 4), 0.5, dtype=np.float32)
    result, counts = vision._filter_proposals(scores, classes, boxes, (64, 64), frozenset({0}))
    assert result == () and counts.low_score == 100
    scores[:2] = 0.8
    boxes[0] = (0.5, 0.5, 0.25, 0.25)
    boxes[1] = (0.5, 0.5, 0.21875, 0.21875)
    result, counts = vision._filter_proposals(scores, classes, boxes, (64, 64), frozenset({0}))
    assert result[0].crop(Image.new("RGB", (64, 64))).size == (16, 16)
    assert len(result) == 1 and counts.too_small == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_detector_invalid_outputs_are_not_silently_filtered(bad: float) -> None:
    scores = np.ones(100, dtype=np.float32)
    classes = np.ones(100, dtype=np.int64)
    boxes = np.full((100, 4), 0.5, dtype=np.float32)
    for bad_scores, bad_boxes in ((True, False), (False, True)):
        invalid_scores, invalid_boxes = scores.copy(), boxes.copy()
        if bad_scores:
            invalid_scores[99] = bad
        if bad_boxes:
            invalid_boxes[99, 0] = bad
        with pytest.raises(ValueError, match="detector output"):
            vision._filter_proposals(
                invalid_scores, classes, invalid_boxes, (64, 64), frozenset({0})
            )


class FakeDetector:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            num_detection_tokens=100,
            num_labels=91,
            hidden_size=192,
            id2label={index: "N/A" if index == 0 else f"class-{index}" for index in range(91)},
        )
        self.logits = torch.full((1, 100, 92), -20.0)
        self.logits[:, :, -1] = 20
        self.logits[:, :24, 1] = 25
        self.boxes = torch.full((1, 100, 4), 0.5)
        self.evaluating = False
        self.calls = 0

    def to(self, *, device: str, dtype: torch.dtype) -> FakeDetector:
        assert device == "cpu" and dtype == torch.float32
        return self

    def eval(self) -> FakeDetector:
        self.evaluating = True
        return self

    def __call__(self, *, pixel_values: torch.Tensor) -> SimpleNamespace:
        assert self.evaluating and torch.is_inference_mode_enabled()
        assert pixel_values.shape[0] == 1 and pixel_values.dtype == torch.float32
        self.calls += 1
        return SimpleNamespace(logits=self.logits, pred_boxes=self.boxes)


class FakeDescriptor:
    def __init__(self) -> None:
        self.config = SimpleNamespace(hidden_size=384, patch_size=14, num_hidden_layers=12)
        self.hidden = torch.ones((4, 257, 384), dtype=torch.float32)
        self.hidden[:, 0, :] = 0
        self.hidden[:, 0, 0] = 3
        self.hidden[:, 0, 1] = 4
        self.evaluating = False
        self.calls = 0

    def to(self, *, device: str, dtype: torch.dtype) -> FakeDescriptor:
        assert device == "cpu" and dtype == torch.float32
        return self

    def eval(self) -> FakeDescriptor:
        self.evaluating = True
        return self

    def __call__(self, *, pixel_values: torch.Tensor) -> SimpleNamespace:
        assert self.evaluating and torch.is_inference_mode_enabled()
        self.calls += 1
        return SimpleNamespace(last_hidden_state=self.hidden[: pixel_values.shape[0]])


@dataclass
class SyntheticDistribution:
    root: Path
    name: str
    version: str

    @property
    def metadata_path(self) -> Path:
        return self.root / f"{self.name}.dist-info"

    @property
    def content_path(self) -> Path:
        return self.root / self.name / "synthetic-runtime.bin"

    def write(self, body: bytes) -> None:
        """Valid synthetic RECORD; changing content does not change version text."""
        self.metadata_path.mkdir(parents=True, exist_ok=True)
        self.content_path.parent.mkdir(parents=True, exist_ok=True)
        metadata = self.metadata_path / "METADATA"
        metadata.write_text(f"Name: {self.name}\nVersion: {self.version}\n", encoding="ascii")
        self.content_path.write_bytes(body)
        records: list[str] = []
        for path in (metadata, self.content_path):
            raw = path.read_bytes()
            digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
            records.append(f"{path.relative_to(self.root).as_posix()},sha256={digest},{len(raw)}")
        records.append(f"{self.name}.dist-info/RECORD,,")
        (self.metadata_path / "RECORD").write_text("\n".join(records) + "\n", encoding="ascii")


@pytest.fixture
def installed_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, SyntheticDistribution]:
    # Exercise genuine numerical_runtime_identity and RECORD verification without
    # repeatedly hashing the large installed Torch wheel in synthetic model tests.
    original_distribution = importlib.metadata.distribution
    distributions = {
        name: SyntheticDistribution(
            tmp_path / "installed-runtime", name, original_distribution(name).version
        )
        for name in vision._RUNTIME_DISTRIBUTIONS
    }
    for name, distribution in distributions.items():
        distribution.write(f"synthetic {name} runtime".encode())

    def distribution_for(name: str) -> importlib.metadata.Distribution:
        if name in distributions:
            return importlib.metadata.PathDistribution(distributions[name].metadata_path)
        return original_distribution(name)

    monkeypatch.setattr(importlib.metadata, "distribution", distribution_for)
    return distributions


@dataclass
class Loaders:
    root: Path
    detector: FakeDetector
    descriptor: FakeDescriptor
    calls: list[tuple[str, str, dict[str, object]]]
    info: dict[str, list[str]]
    change_after_load: Callable[[], None]
    runtime: dict[str, SyntheticDistribution]


@pytest.fixture
def loaders(
    artifacts: Artifacts,
    monkeypatch: pytest.MonkeyPatch,
    installed_runtime: dict[str, SyntheticDistribution],
) -> Loaders:
    import transformers

    vision.acquire_models(artifacts.root)
    result = Loaders(
        artifacts.root,
        FakeDetector(),
        FakeDescriptor(),
        [],
        {key: [] for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")},
        lambda: None,
        installed_runtime,
    )

    def processor(*, images: list[Image.Image], return_tensors: str) -> dict[str, torch.Tensor]:
        assert return_tensors == "pt"
        assert torch.is_inference_mode_enabled()
        return {"pixel_values": torch.zeros((len(images), 3, 224, 224), dtype=torch.float32)}

    def loader(name: str) -> SimpleNamespace:
        def load(root: str, **kwargs: object) -> object:
            assert os.environ["HF_HUB_OFFLINE"] == "1"
            assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
            assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
            result.calls.append((name, root, kwargs))
            if "Processor" in name:
                return processor
            if name == "Dinov2Model":
                result.change_after_load()
                return result.descriptor, result.info
            return result.detector, result.info

        return SimpleNamespace(from_pretrained=load)

    # Resolve all lazy imports before patching; importing a sibling model can
    # otherwise replace earlier attributes in Transformers' lazy module registry.
    names = ("YolosImageProcessor", "BitImageProcessor", "YolosForObjectDetection", "Dinov2Model")
    classes = {name: getattr(transformers, name) for name in names}
    for name, model_class in classes.items():
        monkeypatch.setattr(model_class, "from_pretrained", loader(name).from_pretrained)
    return result


def test_offline_pretrained_loading_and_real_filter_descriptor_path(loaders: Loaders) -> None:
    models = vision.VisionModels(loaders.root, threads=2, batch_size=4)
    assert [name for name, _, _ in loaders.calls] == [
        "YolosImageProcessor",
        "BitImageProcessor",
        "YolosForObjectDetection",
        "Dinov2Model",
    ]
    for name, root, kwargs in loaders.calls:
        assert root == str(loaders.root / ("yolos-tiny" if "Yolos" in name else "dinov2-small"))
        assert kwargs["local_files_only"] is True
        if "Processor" not in name:
            assert kwargs == {
                "local_files_only": True,
                "trust_remote_code": False,
                "use_safetensors": True,
                "dtype": torch.float32,
                "attn_implementation": "eager",
                "output_loading_info": True,
                "ignore_mismatched_sizes": False,
            }
    assert models.last_proposal_counts is None
    proposals = models.proposals(Image.new("RGB", (64, 64)))
    assert len(proposals) == 20
    assert models.last_proposal_counts == vision.ProposalCounts(100, 76, 0, 0, 4, 20)
    assert loaders.detector.calls == 1
    rows = models.descriptors([Image.new("RGB", (64, 64)), Image.new("RGB", (16, 16))])
    assert rows.shape == (2, 384) and rows.dtype == np.float32
    np.testing.assert_allclose(rows[:, :2], [[0.6, 0.8], [0.6, 0.8]])
    np.testing.assert_array_equal(rows[:, 2:], 0)
    assert rows.flags.owndata and rows.flags.c_contiguous
    assert loaders.descriptor.calls == 1
    assert models.identity["instance_accuracy_established"] is False
    assert "center-crop" in str(models.identity["descriptor"])


def test_identity_binds_source_helpers_runtime_content_and_effective_policy(
    loaders: Loaders,
) -> None:
    models = vision.VisionModels(loaders.root)
    identity = models.identity
    implementation = object_value(identity["implementation"])
    source = object_value(implementation["object_search_vision.py"])
    raw = Path(vision.__file__).read_bytes()
    assert source == {"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    assert implementation["memotrace_ml_implementation_sha256"] == (
        runtime_identity.implementation_digest()
    )
    assert identity["implementation_sha256"] == fingerprint(implementation)
    runtime = object_value(identity["runtime"])
    assert runtime["version"] == "numerical-runtime-v2"
    distributions = object_value(runtime["distributions"])
    assert set(distributions) == {
        "torch",
        "transformers",
        "tokenizers",
        "numpy",
        "pillow",
        "safetensors",
        "threadpoolctl",
    }
    for name in distributions:
        assert distributions[name] == runtime_identity.distribution_record_identity(name)
    for name in ("python", "libc", "cpu_features", "torch_build"):
        assert runtime[name]
    build = object_value(runtime["torch_build"])
    assert build == vision._torch_build_identity()
    assert build["cpu_capability"] == torch.backends.cpu.get_cpu_capability()
    policy = object_value(identity["policy"])
    assert policy["source"] == {"min_edge": 32, "max_edge": 2048, "max_pixels": 4_000_000}
    assert policy["crop"] == {"min_edge": 16, "max_edge": 2048, "max_pixels": 4_000_000}
    detector = object_value(policy["detector"])
    assert detector["score_threshold"] == 0.20
    assert detector["effective_score_threshold_float32"] == float(np.float32(0.20))
    assert detector["max_proposals"] == 20
    assert models.model_fingerprint == fingerprint(identity)
    models.identity = identity
    models.model_fingerprint = models.model_fingerprint
    with pytest.raises(ValueError, match="cannot replace bound vision fingerprint"):
        models.model_fingerprint = "0" * 64
    # Report consumers cannot silently rewrite a live instance's bound snapshot.
    object_value(identity["policy"])["source"] = {}
    with pytest.raises(ValueError, match="cannot replace bound vision identity"):
        models.identity = identity
    assert models.identity["policy"] == policy | {
        "source": {"min_edge": 32, "max_edge": 2048, "max_pixels": 4_000_000}
    }


@pytest.mark.parametrize(
    "name,value",
    [
        ("SCORE_THRESHOLD", 0.999),
        ("MAX_PROPOSALS", 10),
        ("MIN_CROP_EDGE", 20),
        ("MIN_EDGE", 40),
        ("MAX_EDGE", 1024),
        ("MAX_PIXELS", 2_000_000),
        ("MAX_BATCH_SIZE", 3),
        ("_DETECTOR_MAX_EDGE", 1024),
        ("_DESCRIPTOR_EDGE", 448),
        ("_NORM_RTOL", 1e-4),
        ("_NORM_ATOL", 1e-5),
    ],
)
def test_effective_numeric_policy_changes_fingerprint(
    loaders: Loaders, monkeypatch: pytest.MonkeyPatch, name: str, value: int | float
) -> None:
    first = vision.VisionModels(loaders.root, batch_size=2)
    before = first.model_fingerprint
    monkeypatch.setattr(vision, name, value)
    changed = vision.VisionModels(loaders.root, batch_size=2)
    assert changed.model_fingerprint != before
    with pytest.raises(ValueError, match="policy changed after load"):
        _ = first.model_fingerprint
    if name in {"SCORE_THRESHOLD", "MAX_PROPOSALS"}:
        result = changed.proposals(Image.new("RGB", (64, 64)))
        assert len(result) == (0 if name == "SCORE_THRESHOLD" else 10)


def test_source_bytes_change_fingerprint_and_final_getters_fail_closed(
    loaders: Loaders, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "vision-copy.py"
    source.write_bytes(Path(vision.__file__).read_bytes())
    monkeypatch.setattr(vision, "__file__", str(source))
    first = vision.VisionModels(loaders.root)
    before = first.model_fingerprint
    source.write_bytes(source.read_bytes() + b"\n# synthetic source revision\n")
    for name in ("identity", "model_fingerprint"):
        with pytest.raises(ValueError, match="implementation changed after load"):
            getattr(first, name)
    with pytest.raises(ValueError, match="implementation changed after load"):
        first.descriptors([Image.new("RGB", (64, 64))])
    assert vision.VisionModels(loaders.root).model_fingerprint != before


def test_helper_source_bytes_change_fingerprint(
    loaders: Loaders, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "synthetic-package"
    package.mkdir()
    source = package / "common.py"
    source.write_bytes(b"# synthetic helper revision one\n")
    monkeypatch.setattr(
        vision, "implementation_digest", lambda: runtime_identity.implementation_digest(package)
    )
    first = vision.VisionModels(loaders.root)
    before = first.model_fingerprint
    source.write_bytes(b"# synthetic helper revision two\n")
    with pytest.raises(ValueError, match="implementation changed after load"):
        _ = first.identity
    assert vision.VisionModels(loaders.root).model_fingerprint != before


def test_installed_runtime_content_changes_fingerprint_without_version_change(
    loaders: Loaders,
) -> None:
    first = vision.VisionModels(loaders.root)
    before = first.model_fingerprint
    original_runtime = object_value(object_value(first.identity["runtime"])["distributions"])
    loaders.runtime["torch"].write(b"different synthetic torch runtime, same version")
    changed = vision.VisionModels(loaders.root)
    new_runtime = object_value(object_value(changed.identity["runtime"])["distributions"])
    original_torch = object_value(original_runtime["torch"])
    new_torch = object_value(new_runtime["torch"])
    assert original_torch["version"] == new_torch["version"]
    assert original_torch["content_sha256"] != new_torch["content_sha256"]
    assert changed.model_fingerprint != before


def test_installed_runtime_record_tamper_fails_closed(loaders: Loaders) -> None:
    path = loaders.runtime["torch"].content_path
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(ValueError, match="RECORD digest mismatch"):
        vision.VisionModels(loaders.root)


@pytest.mark.parametrize("component", ["python", "libc", "cpu_features", "torch_cpu"])
def test_numerical_runtime_changes_fingerprint(
    loaders: Loaders, monkeypatch: pytest.MonkeyPatch, component: str
) -> None:
    before = vision.VisionModels(loaders.root).model_fingerprint
    if component == "python":
        monkeypatch.setattr(platform, "python_version", lambda: "3.12.synthetic")
    elif component == "libc":
        monkeypatch.setattr(platform, "libc_ver", lambda: ("synthetic", "1.2.3"))
    elif component == "cpu_features":
        monkeypatch.setattr(runtime_identity, "cpu_features", lambda: ["synthetic_cpu_feature"])
    else:
        monkeypatch.setattr(torch.backends.cpu, "get_cpu_capability", lambda: "SYNTHETIC-CPU")
    assert vision.VisionModels(loaders.root).model_fingerprint != before


def test_relocation_and_mtime_do_not_change_identity(
    loaders: Loaders, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "original-vision.py"
    source.write_bytes(Path(vision.__file__).read_bytes())
    monkeypatch.setattr(vision, "__file__", str(source))
    helper_root = tmp_path / "original-helpers"
    helper_root.mkdir()
    (helper_root / "common.py").write_bytes(b"# synthetic helper\n")
    monkeypatch.setattr(
        vision, "implementation_digest", lambda: runtime_identity.implementation_digest(helper_root)
    )
    first = vision.VisionModels(loaders.root)
    before, identity = first.model_fingerprint, first.identity
    new_source = tmp_path / "relocated-vision.py"
    source.rename(new_source)
    os.utime(new_source, (100, 100))
    monkeypatch.setattr(vision, "__file__", str(new_source))
    new_helpers = tmp_path / "relocated-helpers"
    helper_root.rename(new_helpers)
    helper_root = new_helpers
    new_models = tmp_path / "relocated-models"
    loaders.root.rename(new_models)
    new_runtime = tmp_path / "relocated-runtime"
    loaders.runtime["torch"].root.rename(new_runtime)
    for distribution in loaders.runtime.values():
        distribution.root = new_runtime
    changed = vision.VisionModels(new_models)
    assert changed.model_fingerprint == before
    assert changed.identity == identity
    assert str(tmp_path).encode() not in canonical(identity)


def test_source_change_during_load_is_detected(
    loaders: Loaders, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "vision-copy.py"
    source.write_bytes(Path(vision.__file__).read_bytes())
    monkeypatch.setattr(vision, "__file__", str(source))

    def change() -> None:
        source.write_bytes(source.read_bytes() + b"\n# synthetic in-load source edit\n")

    loaders.change_after_load = change
    with pytest.raises(ValueError, match="implementation changed during load"):
        vision.VisionModels(loaders.root)


def test_source_change_during_inference_rejects_output(
    loaders: Loaders, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "vision-copy.py"
    source.write_bytes(Path(vision.__file__).read_bytes())
    monkeypatch.setattr(vision, "__file__", str(source))
    models = vision.VisionModels(loaders.root)
    original_call = FakeDescriptor.__call__

    def changed_call(self: FakeDescriptor, *, pixel_values: torch.Tensor) -> SimpleNamespace:
        output = original_call(self, pixel_values=pixel_values)
        source.write_bytes(source.read_bytes() + b"\n# synthetic in-inference source edit\n")
        return output

    monkeypatch.setattr(FakeDescriptor, "__call__", changed_call)
    with pytest.raises(ValueError, match="implementation changed after load"):
        models.descriptors([Image.new("RGB", (64, 64))])


@pytest.mark.parametrize(
    "key", ["missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"]
)
def test_any_inexact_pretrained_loading_fails(loaders: Loaders, key: str) -> None:
    loaders.info[key] = ["synthetic rejected weight"]
    with pytest.raises(ValueError, match="load exactly"):
        vision.VisionModels(loaders.root)


def test_absent_loading_info_is_rejected() -> None:
    invalid: tuple[object, ...] = (None, {}, {"missing_keys": []}, {"missing_keys": ()})
    for value in invalid:
        with pytest.raises(ValueError, match="load exactly"):
            vision._loading_info(value)


def test_post_load_integrity_is_reverified(loaders: Loaders) -> None:
    def tamper() -> None:
        (loaders.root / "dinov2-small" / "README.md").write_bytes(b"tampered")

    loaders.change_after_load = tamper
    with pytest.raises(ValueError):
        vision.VisionModels(loaders.root)


@pytest.mark.parametrize("kind", ["architecture", "labels", "no-na"])
def test_invalid_architecture_or_labels_fail(loaders: Loaders, kind: str) -> None:
    if kind == "architecture":
        loaders.descriptor.config.hidden_size = 768
    elif kind == "labels":
        loaders.detector.config.id2label = {"0": "N/A"}
    else:
        loaders.detector.config.id2label[0] = "class-zero"
    with pytest.raises(ValueError):
        vision.VisionModels(loaders.root)


@pytest.mark.parametrize(
    "threads,batch_size", [(True, 4), (0, 4), (17, 4), (4, 0), (4, 5), (4, 1.5)]
)
def test_runtime_bounds_rejected_before_filesystem(threads: object, batch_size: object) -> None:
    with pytest.raises(ValueError, match="runtime bounds"):
        vision.VisionModels(Path("relative"), cast(int, threads), cast(int, batch_size))


@pytest.mark.parametrize("size", [(31, 64), (64, 31), (2049, 64), (2048, 2048)])
def test_source_image_bounds(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        vision.validate_image(Image.new("RGB", size))


def test_rgb_and_exact_source_bounds() -> None:
    vision.validate_image(Image.new("RGB", (32, 2048)))
    vision.validate_image(Image.new("RGB", (2000, 2000)))
    with pytest.raises(ValueError, match="RGB"):
        vision.validate_image(Image.new("RGBA", (32, 32)))


def test_workload_bounds_are_checked_before_processing(loaders: Loaders) -> None:
    models = vision.VisionModels(loaders.root, batch_size=2)
    image = Image.new("RGB", (64, 64))

    def endless() -> Iterator[Image.Image]:
        while True:
            yield image

    for images in ([], [image] * 3, endless(), [Image.new("RGB", (15, 16))]):
        with pytest.raises(ValueError):
            models.descriptors(cast(Sequence[Image.Image], images))
    with pytest.raises(ValueError):
        models.proposals(Image.new("RGB", (31, 32)))
    assert loaders.detector.calls == loaders.descriptor.calls == 0


@pytest.mark.parametrize("failure", ["nan", "inf", "zero", "shape", "dtype", "overflow"])
def test_invalid_descriptor_outputs_fail(loaders: Loaders, failure: str) -> None:
    models = vision.VisionModels(loaders.root)
    if failure == "shape":
        loaders.descriptor.hidden = torch.ones((4, 258, 384))
    elif failure == "dtype":
        loaders.descriptor.hidden = loaders.descriptor.hidden.to(torch.float64)
    elif failure == "zero":
        loaders.descriptor.hidden[:, 0, :] = 0
    elif failure == "overflow":
        loaders.descriptor.hidden[:, 0, :] = torch.finfo(torch.float32).max
    else:
        loaders.descriptor.hidden[0, -1, -1] = float(failure)
    with pytest.raises(ValueError):
        models.descriptors([Image.new("RGB", (64, 64))])


def test_failed_proposals_clear_previous_counts(loaders: Loaders) -> None:
    models = vision.VisionModels(loaders.root)
    image = Image.new("RGB", (64, 64))
    models.proposals(image)
    assert models.last_proposal_counts is not None
    loaders.detector.logits[0, 99, 91] = float("nan")
    with pytest.raises(ValueError):
        models.proposals(image)
    assert models.last_proposal_counts is None


def test_real_locked_bit_processor_center_crop_loses_periphery() -> None:
    from transformers import BitImageProcessor

    # Synthetic config exercises the real locked processor, not fake embeddings as
    # accuracy evidence. Actual model acquisition separately pins its config bytes.
    processor = BitImageProcessor(
        size={"shortest_edge": 256},
        crop_size={"height": 224, "width": 224},
        do_rescale=False,
        do_normalize=False,
    )
    image = Image.new("RGB", (1024, 256), (0, 255, 0))
    image.paste((255, 0, 0), (0, 0, 256, 256))
    pixels = processor(images=[image], return_tensors="np")["pixel_values"]
    assert pixels.shape == (1, 3, 224, 224)
    assert np.all(pixels[0, 0] == 0) and np.all(pixels[0, 1] == 255)


def test_cli_verify_safe_identity_and_sanitized_failure(
    artifacts: Artifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    identity = vision.acquire_models(artifacts.root)
    vision.main(["verify", "--root", str(artifacts.root)])
    assert capsys.readouterr().out == canonical(identity).decode() + "\n"
    with pytest.raises(SystemExit, match="artifact operation failed"):
        vision.main(["verify", "--root", str(artifacts.root / "missing")])
