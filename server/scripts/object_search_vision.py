"""Bounded experimental YOLOS-Tiny proposals and DINOv2-small crop descriptors.

Public runner API (all filesystem roots must be explicit, absolute, outside Git):

* ``acquire_models(root: Path) -> dict[str, JSON]`` is the ONLY network operation.
* ``verify_models(root: Path) -> dict[str, JSON]`` checks bytes and exact inventory
  offline, returning path-free, JSON-serializable artifact identity.
* ``VisionModels(root, threads=4, batch_size=4)`` loads both verified pretrained
  models locally, CPU float32/eager/eval. Use one instance serially, before other
  Torch work: thread settings are process-global, not per-request isolation.
* ``models.proposals(image) -> tuple[Proposal, ...]`` takes ONE upright RGB image,
  edges 32..2048, at most 4,000,000 pixels. ``last_proposal_counts`` describes the
  last successful call (None after failure). There is no implicit full-image row.
* ``full_image_fallback(image) -> FullImageFallback`` creates that separate region.
  Both region types expose normalized XYXY ``box``, half-open integer ``pixel_box``,
  and ``crop(image)``. Boxes are normalized AFTER clip/floor/ceil rasterization.
* ``models.descriptors(images: Sequence[Image.Image]) -> NDArray[np.float32]``
  accepts ONE batch, 1..batch_size (maximum 4), returning independent (N,384) L2
  rows. The caller chunks work. Detector-derived crops may have 16-pixel edges;
  source/query images should be checked with ``validate_image`` (32-pixel minimum).
* ``models.identity`` and ``models.model_fingerprint`` retain their getter API;
  reading either at report finalization rechecks source bytes and effective policy.
  Inference also checks these before and after each call. The fingerprint binds this
  file, packaged helper implementation bytes, numeric policy, installed distribution
  content, Python/libc and Torch CPU/build settings. Relocation does not change it.
  Keep runtime installations fixed for the lifetime of the instance: distribution
  content is verified at load, not rehashed for every crop.

Pinned BitImageProcessor resizes and CENTER CROPS queries and proposal crops;
peripheral content can be lost. These candidates do not establish instance-search
accuracy, stable object identity, or tracking. No text encoder or model fallback.
Inputs must already have the intended orientation; this module neither opens image
paths nor applies EXIF/ICC transforms. Crop coordinates refer to those input pixels.

Acquisition retains exactly four pinned files plus manifest.json in each of
root/yolos-tiny and root/dinov2-small. The cards declare Apache-2.0. Git blob SHA-1
pins hash ``b'blob ' + decimal_length + b'\\0' + bytes``, NOT raw bytes. Receipts
separately bind actual raw SHA-256, length and immutable revision URL. A manifest
seals a complete model; partial unsealed roots resume only after verifying every
retained file against independent pins. Unexpected files (including stale stages,
bin/pickle weights and .partial files), tamper and symlinks fail closed.
Keep roots read-only during inference: pre/post-load checks do not defeat a
malicious same-UID change-and-restore race. This is not a sandbox.

From server/, with the existing locked ML environment installed:
  uv run --locked --project ml python -m scripts.object_search_vision acquire --root ABSOLUTE_ROOT
  uv run --locked --project ml python -m scripts.object_search_vision verify --root ABSOLUTE_ROOT
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import stat
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast

import numpy as np
from memotrace_ml.artifacts import directory, entries, read_bytes, reader, write_once
from memotrace_ml.common import JSON, canonical, external_root, fingerprint
from memotrace_ml.identity import implementation_digest, numerical_runtime_identity
from numpy.typing import NDArray
from PIL import Image

if TYPE_CHECKING:
    import torch

MAX_PIXELS = 4_000_000
MIN_EDGE = 32
MAX_EDGE = 2048
MIN_CROP_EDGE = 16
MAX_BATCH_SIZE = 4
MAX_PROPOSALS = 20
SCORE_THRESHOLD = 0.20
DIMENSION = 384
_QUERIES = 100
_LABELS = 91
_MANIFEST_LIMIT = 16_384
_SOURCE_LIMIT = 1024 * 1024
_MAX_THREADS = 16
_DETECTOR_MIN_EDGE = 16
_DETECTOR_MAX_EDGE = 1333
_DESCRIPTOR_EDGE = 224
_DESCRIPTOR_PATCH = 14
_DESCRIPTOR_TOKENS = 257
_NORM_RTOL = 1e-5
_NORM_ATOL = 1e-6
_RUNTIME_DISTRIBUTIONS = (
    "torch",
    "transformers",
    "tokenizers",
    "numpy",
    "pillow",
    "safetensors",
    "threadpoolctl",
)

type Box = tuple[float, float, float, float]
type PixelBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class _Artifact:
    name: str
    byte_length: int
    kind: Literal["sha256", "git_blob_sha1"]
    digest: str


@dataclass(frozen=True)
class _Checkpoint:
    directory: str
    model_id: str
    revision: str
    files: tuple[_Artifact, ...]


_CHECKPOINTS = (
    _Checkpoint(
        "yolos-tiny",
        "hustvl/yolos-tiny",
        "95a90f3c189fbfca3bcfc6d7315b9e84d95dc2de",
        (
            _Artifact(
                "model.safetensors",
                25_978_888,
                "sha256",
                "5a6a017a20cb522dd347271fa5bd670467e456176aaccd940090e50985ac6e74",
            ),
            _Artifact(
                "config.json", 4133, "git_blob_sha1", "9b1dc5fbaca6c50cb8a92488448be33bf7a60260"
            ),
            _Artifact(
                "preprocessor_config.json",
                291,
                "git_blob_sha1",
                "79bb34ebb0f2c7ba7a8f0a3d99148a2cfb61019c",
            ),
            _Artifact(
                "README.md", 4618, "git_blob_sha1", "e96ad2f972e86d4a7d46005fdc3410f15defdc14"
            ),
        ),
    ),
    _Checkpoint(
        "dinov2-small",
        "facebook/dinov2-small",
        "ed25f3a31f01632728cabb09d1542f84ab7b0056",
        (
            _Artifact(
                "model.safetensors",
                88_249_960,
                "sha256",
                "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1",
            ),
            _Artifact(
                "config.json", 547, "git_blob_sha1", "5664b325e6258d3960fad8c4c1cff958f3cc2272"
            ),
            _Artifact(
                "preprocessor_config.json",
                436,
                "git_blob_sha1",
                "ff5b47c2edcd1d3556d63c01a65d93b58b9efce1",
            ),
            _Artifact(
                "README.md", 3033, "git_blob_sha1", "6b3380957df44ed203ec1d5102e1245accbbbba9"
            ),
        ),
    ),
)


def _root(path: Path, *, create: bool = False) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise ValueError("model root must be an explicit absolute external path")
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise ValueError("model root must be outside Git")
    if create:
        return external_root(path)
    with directory(path):
        pass
    return path


def _url(checkpoint: _Checkpoint, artifact: _Artifact) -> str:
    return (
        f"https://huggingface.co/{checkpoint.model_id}/resolve/"
        f"{checkpoint.revision}/{artifact.name}?download=true"
    )


def _validate_blob(artifact: _Artifact, body: bytes) -> None:
    if artifact.kind != "git_blob_sha1" or len(body) != artifact.byte_length:
        raise ValueError("invalid Git blob length or pin kind")
    header = f"blob {len(body)}\0".encode("ascii")
    if hashlib.sha1(header + body).hexdigest() != artifact.digest:
        raise ValueError("Git blob SHA-1 mismatch")


def _receipt(root: Path, checkpoint: _Checkpoint, artifact: _Artifact) -> dict[str, JSON]:
    with reader(root / artifact.name, artifact.byte_length) as source:
        if os.fstat(source.fileno()).st_size != artifact.byte_length:
            raise ValueError("model artifact length mismatch")
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        if artifact.kind == "sha256":
            if digest != artifact.digest:
                raise ValueError("model artifact SHA-256 mismatch")
        else:
            source.seek(0)
            _validate_blob(artifact, source.read(artifact.byte_length + 1))
    return {
        "source": _url(checkpoint, artifact),
        "byte_length": artifact.byte_length,
        "sha256": digest,
        "pin": {"kind": artifact.kind, "digest": artifact.digest},
    }


def _manifest(root: Path, checkpoint: _Checkpoint) -> dict[str, JSON]:
    return {
        "version": "object-search-vision-artifacts-v1",
        "model_id": checkpoint.model_id,
        "revision": checkpoint.revision,
        "license": "Apache-2.0",
        "license_evidence": "pinned README.md model card declaration",
        "files": {
            artifact.name: _receipt(root, checkpoint, artifact) for artifact in checkpoint.files
        },
    }


def _check_model(root: Path, checkpoint: _Checkpoint, *, partial: bool) -> dict[str, JSON] | None:
    names = set(entries(root))
    expected = {artifact.name for artifact in checkpoint.files}
    sealed = "manifest.json" in names
    if names - (expected | {"manifest.json"}):
        raise ValueError("unexpected model inventory")
    if sealed or not partial:
        if names != expected | {"manifest.json"}:
            raise ValueError("incomplete sealed model inventory")
        manifest = _manifest(root, checkpoint)
        if read_bytes(root / "manifest.json", _MANIFEST_LIMIT) != canonical(manifest) + b"\n":
            raise ValueError("model manifest mismatch")
        return manifest
    for artifact in checkpoint.files:
        if artifact.name in names:
            _receipt(root, checkpoint, artifact)
    return None


def verify_models(root: Path) -> dict[str, JSON]:
    """Offline, read-only exact verification; return only public identity, never paths."""
    root = _root(root)
    if set(entries(root)) != {checkpoint.directory for checkpoint in _CHECKPOINTS}:
        raise ValueError("unexpected vision root inventory")
    manifests: dict[str, JSON] = {}
    for checkpoint in _CHECKPOINTS:
        manifests[checkpoint.directory] = _check_model(
            root / checkpoint.directory, checkpoint, partial=False
        )
    identity: dict[str, JSON] = {"version": "object-search-vision-models-v1", "models": manifests}
    return {**identity, "fingerprint": fingerprint(identity)}


def acquire_models(root: Path) -> dict[str, JSON]:
    """Explicit bounded network acquisition/resume; verify stages BEFORE publication.

    No network starts until every retained artifact in both model directories has
    passed preflight. A failed download leaves only independently verifiable files;
    manifests are published last, without clobbering. There is no repair-on-tamper.
    """
    from memotrace_ml.acquire import download

    root = _root(root, create=True)
    names = set(entries(root))
    if names - {checkpoint.directory for checkpoint in _CHECKPOINTS}:
        raise ValueError("unexpected vision root inventory")
    for checkpoint in _CHECKPOINTS:
        if checkpoint.directory in names:
            _check_model(root / checkpoint.directory, checkpoint, partial=True)
    for checkpoint in _CHECKPOINTS:
        model_root = _root(root / checkpoint.directory, create=True)
        for artifact in checkpoint.files:
            retained_sha256: str | None = None
            if artifact.name in entries(model_root):
                retained_sha256 = cast(str, _receipt(model_root, checkpoint, artifact)["sha256"])
            if artifact.kind == "git_blob_sha1":
                # Bind loop state explicitly; downloader calls this on its own stage.
                def validate(body: bytes, pinned: _Artifact = artifact) -> None:
                    _validate_blob(pinned, body)

                download(
                    _url(checkpoint, artifact),
                    model_root / artifact.name,
                    artifact.byte_length,
                    expected=retained_sha256,
                    expected_length=artifact.byte_length,
                    seconds=1800,
                    validate=validate,
                )
            else:
                download(
                    _url(checkpoint, artifact),
                    model_root / artifact.name,
                    artifact.byte_length,
                    expected=artifact.digest,
                    expected_length=artifact.byte_length,
                    seconds=1800,
                )
        write_once(
            model_root / "manifest.json", canonical(_manifest(model_root, checkpoint)) + b"\n"
        )
    return verify_models(root)


def _validate_image(image: Image.Image, minimum: int) -> None:
    if not isinstance(image, Image.Image) or image.mode != "RGB":
        raise ValueError("image must be a PIL RGB image")
    width, height = image.size
    if not (
        minimum <= width <= MAX_EDGE
        and minimum <= height <= MAX_EDGE
        and width * height <= MAX_PIXELS
    ):
        raise ValueError("image dimensions exceed vision bounds")


def validate_image(image: Image.Image) -> None:
    """Validate a source frame or query before inference/cropping: RGB, 32..2048, 4MP."""
    _validate_image(image, MIN_EDGE)


def _normalized(pixel_box: PixelBox, size: tuple[int, int]) -> Box:
    left, top, right, bottom = pixel_box
    width, height = size
    return (left / width, top / height, right / width, bottom / height)


def _crop(image: Image.Image, pixel_box: PixelBox, image_size: tuple[int, int]) -> Image.Image:
    validate_image(image)
    left, top, right, bottom = pixel_box
    width, height = image.size
    if (
        image.size != image_size
        or any(type(value) is not int for value in pixel_box)
        or not (0 <= left < right <= width and 0 <= top < bottom <= height)
        or right - left < MIN_CROP_EDGE
        or bottom - top < MIN_CROP_EDGE
    ):
        raise ValueError("invalid crop geometry or source size")
    return image.crop(pixel_box)


@dataclass(frozen=True)
class Proposal:
    """Scored detector region; box and crop refer to the SAME half-open pixels."""

    box: Box
    pixel_box: PixelBox
    score: float
    class_id: int
    query_index: int
    image_size: tuple[int, int]

    def crop(self, image: Image.Image) -> Image.Image:
        return _crop(image, self.pixel_box, self.image_size)


@dataclass(frozen=True)
class FullImageFallback:
    """Explicit full-image region, deliberately without a detector score/class ID."""

    box: Box
    pixel_box: PixelBox
    image_size: tuple[int, int]

    def crop(self, image: Image.Image) -> Image.Image:
        return _crop(image, self.pixel_box, self.image_size)


def full_image_fallback(image: Image.Image) -> FullImageFallback:
    """Return a separate full-image region; never consumes the 20-proposal budget."""
    validate_image(image)
    return FullImageFallback((0.0, 0.0, 1.0, 1.0), (0, 0, *image.size), image.size)


@dataclass(frozen=True)
class ProposalCounts:
    """Disjoint filtering counters: candidates = filtered + truncated + returned.

    Filtering order: score <= .20, then N/A class, then clipped raster <16px.
    Invalid/nonfinite tensors reject the entire call rather than disappear here.
    """

    candidates: int
    low_score: int
    excluded_class: int
    too_small: int
    truncated: int
    returned: int

    @property
    def filtered(self) -> int:
        return self.low_score + self.excluded_class + self.too_small


def _filter_proposals(
    scores: NDArray[np.float32],
    classes: NDArray[np.int64],
    boxes: NDArray[np.float32],
    image_size: tuple[int, int],
    excluded_classes: frozenset[int],
) -> tuple[tuple[Proposal, ...], ProposalCounts]:
    if (
        scores.shape != (_QUERIES,)
        or classes.shape != (_QUERIES,)
        or boxes.shape != (_QUERIES, 4)
        or scores.dtype != np.float32
        or boxes.dtype != np.float32
        or classes.dtype != np.int64
        or not np.isfinite(scores).all()
        or not np.isfinite(boxes).all()
        or np.any((scores < 0) | (scores > 1))
        or np.any((classes < 0) | (classes >= _LABELS))
        or np.any((boxes < 0) | (boxes > 1))
    ):
        raise ValueError("invalid detector output")
    width, height = image_size
    low_score = excluded_class = too_small = 0
    selected: list[Proposal] = []
    for index in range(_QUERIES):
        score = float(scores[index])
        # Compare in the model's float32 domain, including equality to float32(.20).
        if scores[index] <= np.float32(SCORE_THRESHOLD):
            low_score += 1
            continue
        class_id = int(classes[index])
        if class_id in excluded_classes:
            excluded_class += 1
            continue
        cx, cy, box_width, box_height = (float(value) for value in boxes[index])
        left = math.floor(max(0.0, min(1.0, cx - box_width / 2)) * width)
        top = math.floor(max(0.0, min(1.0, cy - box_height / 2)) * height)
        right = math.ceil(max(0.0, min(1.0, cx + box_width / 2)) * width)
        bottom = math.ceil(max(0.0, min(1.0, cy + box_height / 2)) * height)
        if right - left < MIN_CROP_EDGE or bottom - top < MIN_CROP_EDGE:
            too_small += 1
            continue
        pixels = (left, top, right, bottom)
        selected.append(
            Proposal(_normalized(pixels, image_size), pixels, score, class_id, index, image_size)
        )
    selected.sort(key=lambda proposal: (-proposal.score, proposal.query_index))
    truncated = max(0, len(selected) - MAX_PROPOSALS)
    result = tuple(selected[:MAX_PROPOSALS])
    return result, ProposalCounts(
        _QUERIES, low_score, excluded_class, too_small, truncated, len(result)
    )


class _Processor(Protocol):
    def __call__(
        self, *, images: list[Image.Image], return_tensors: str
    ) -> Mapping[str, torch.Tensor]: ...


class _Detection(Protocol):
    logits: torch.Tensor
    pred_boxes: torch.Tensor


class _Description(Protocol):
    last_hidden_state: torch.Tensor


class _Detector(Protocol):
    def __call__(self, *, pixel_values: torch.Tensor) -> _Detection: ...


class _Descriptor(Protocol):
    def __call__(self, *, pixel_values: torch.Tensor) -> _Description: ...


def _loading_info(info: object) -> None:
    if not isinstance(info, dict) or any(
        info.get(key) != []
        for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
    ):
        raise ValueError("pretrained weights did not load exactly")


def _tensor(value: object, shape: tuple[int, ...]) -> torch.Tensor:
    import torch

    if (
        not isinstance(value, torch.Tensor)
        or tuple(value.shape) != shape
        or value.dtype != torch.float32
        or value.device.type != "cpu"
        or not bool(torch.isfinite(value).all())
    ):
        raise ValueError("invalid vision tensor")
    return value


def _source_bytes() -> bytes:
    """Bounded source read, under the same installation trust boundary as helpers.

    Source installations need not have the private ownership/modes required of
    downloaded model roots. Reject nonregular files, final symlinks and changes
    while reading without imposing acquisition-directory policy on a checkout.
    """
    path = Path(__file__)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _SOURCE_LIMIT:
            raise ValueError("vision source must be a bounded nonempty regular file")
        body = source.read(_SOURCE_LIMIT + 1)
        after = os.fstat(source.fileno())
    current = path.lstat()
    snapshots = {
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        for info in (before, after, current)
    }
    if len(body) != before.st_size or len(snapshots) != 1:
        raise ValueError("vision source changed while reading")
    return body


def _implementation_identity() -> dict[str, JSON]:
    """Hash content, never installation/check-out paths or mtimes.

    The packaged digest covers the entire helper package, including the transitive
    artifact/common/identity dependencies, rather than a fragile hand-picked subset.
    """
    source = _source_bytes()
    return {
        "version": "object-search-vision-implementation-v1",
        "object_search_vision.py": {
            "sha256": hashlib.sha256(source).hexdigest(),
            "byte_length": len(source),
        },
        "memotrace_ml_implementation_sha256": implementation_digest(),
    }


def _torch_build_identity() -> dict[str, JSON]:
    import torch

    return {
        "version": str(torch.__version__),
        "git_version": str(torch.version.git_version),
        "debug": bool(torch.version.debug),
        "cpu_capability": str(torch.backends.cpu.get_cpu_capability()),
        "mkldnn": bool(torch.backends.mkldnn.is_available()),  # type: ignore[no-untyped-call]
        "mkldnn_enabled": bool(torch.backends.mkldnn.enabled),
        "openmp": bool(torch.backends.openmp.is_available()),  # type: ignore[no-untyped-call]
        "cxx11_abi": bool(torch.compiled_with_cxx11_abi()),
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "deterministic_warn_only": torch.is_deterministic_algorithms_warn_only_enabled(),
        "threads": torch.get_num_threads(),
        "interop_threads": torch.get_num_interop_threads(),
    }


def _policy_identity(
    threads: int, batch_size: int, excluded_classes: frozenset[int]
) -> dict[str, JSON]:
    """Use the same numeric constants as inference, including float32 comparison."""
    return {
        "version": "object-search-vision-policy-v1",
        "source": {"min_edge": MIN_EDGE, "max_edge": MAX_EDGE, "max_pixels": MAX_PIXELS},
        "crop": {"min_edge": MIN_CROP_EDGE, "max_edge": MAX_EDGE, "max_pixels": MAX_PIXELS},
        "detector": {
            "batch_size": 1,
            "queries": _QUERIES,
            "labels": _LABELS,
            "score_threshold": SCORE_THRESHOLD,
            "effective_score_threshold_float32": float(np.float32(SCORE_THRESHOLD)),
            "threshold_operator": ">",
            "excluded_class_ids": [int(value) for value in sorted(excluded_classes)],
            "max_proposals": MAX_PROPOSALS,
            "tensor_min_edge": _DETECTOR_MIN_EDGE,
            "tensor_max_edge": _DETECTOR_MAX_EDGE,
            "sort": "score-desc/query-index-asc;class-argmax-first",
            "geometry": "clip-normalized;floor-start-ceil-end;normalize-raster;no-NMS",
        },
        "descriptor": {
            "dimension": DIMENSION,
            "input_edge": _DESCRIPTOR_EDGE,
            "patch_size": _DESCRIPTOR_PATCH,
            "tokens": _DESCRIPTOR_TOKENS,
            "cls_index": 0,
            "norm_min_exclusive": 0,
            "norm_check_rtol": _NORM_RTOL,
            "norm_check_atol": _NORM_ATOL,
            "preprocessing": "pinned-BitImageProcessor-center-crop",
        },
        "workload": {
            "threads": threads,
            "blas_threads": threads,
            "max_threads": _MAX_THREADS,
            "batch_size": batch_size,
            "max_batch_size": MAX_BATCH_SIZE,
        },
    }


class VisionModels:
    """Verified pretrained offline inference; serial use and explicitly bounded calls."""

    dimension = DIMENSION

    def __init__(self, root: Path, threads: int = 4, batch_size: int = 4) -> None:
        if (
            type(threads) is not int
            or not 1 <= threads <= _MAX_THREADS
            or type(batch_size) is not int
            or not 1 <= batch_size <= MAX_BATCH_SIZE
        ):
            raise ValueError("invalid vision runtime bounds")
        identity = verify_models(root)
        implementation = _implementation_identity()
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        import torch
        from threadpoolctl import threadpool_limits
        from transformers import (
            BitImageProcessor,
            Dinov2Model,
            YolosForObjectDetection,
            YolosImageProcessor,
        )

        torch.set_num_threads(threads)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        self._thread_limiter = threadpool_limits(limits=threads)
        self.threads = threads
        self.batch_size = batch_size
        self.last_proposal_counts: ProposalCounts | None = None
        torch_build = _torch_build_identity()
        runtime = numerical_runtime_identity(_RUNTIME_DISTRIBUTIONS, torch_build)
        detector_root = str(root / "yolos-tiny")
        descriptor_root = str(root / "dinov2-small")
        self.detector_processor = cast(
            _Processor,
            YolosImageProcessor.from_pretrained(detector_root, local_files_only=True),
        )
        self.descriptor_processor = cast(
            _Processor,
            BitImageProcessor.from_pretrained(descriptor_root, local_files_only=True),
        )
        detector, info = YolosForObjectDetection.from_pretrained(
            detector_root,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            dtype=torch.float32,
            attn_implementation="eager",
            output_loading_info=True,
            ignore_mismatched_sizes=False,
        )
        _loading_info(info)
        descriptor, info = Dinov2Model.from_pretrained(
            descriptor_root,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            dtype=torch.float32,
            attn_implementation="eager",
            output_loading_info=True,
            ignore_mismatched_sizes=False,
        )
        _loading_info(info)
        if (
            detector.config.num_detection_tokens != _QUERIES
            or detector.config.num_labels != _LABELS
            or detector.config.hidden_size != 192
            or descriptor.config.hidden_size != DIMENSION
            or descriptor.config.patch_size != _DESCRIPTOR_PATCH
            or descriptor.config.num_hidden_layers != 12
        ):
            raise ValueError("unexpected vision architecture")
        labels: object = detector.config.id2label
        if (
            not isinstance(labels, dict)
            or set(labels) != set(range(_LABELS))
            or any(
                type(key) is not int or not isinstance(value, str) for key, value in labels.items()
            )
        ):
            raise ValueError("invalid detector label map")
        self._excluded_classes = frozenset(key for key, value in labels.items() if value == "N/A")
        if not self._excluded_classes:
            raise ValueError("missing detector N/A labels")
        self.detector = cast(_Detector, detector.to(device="cpu", dtype=torch.float32).eval())
        self.descriptor = cast(_Descriptor, descriptor.to(device="cpu", dtype=torch.float32).eval())
        if verify_models(root) != identity:
            raise ValueError("vision artifacts changed during load")
        if _implementation_identity() != implementation:
            raise ValueError("vision implementation changed during load")
        if _torch_build_identity() != torch_build:
            raise ValueError("vision Torch runtime changed during load")
        policy = _policy_identity(threads, batch_size, self._excluded_classes)
        self._implementation_snapshot = canonical(implementation)
        self._policy_snapshot = canonical(policy)
        self._torch_snapshot = canonical(torch_build)
        self._identity: dict[str, JSON] = {
            "version": "object-search-vision-cpu-v2",
            "artifacts": identity,
            "implementation": implementation,
            "implementation_sha256": fingerprint(implementation),
            "runtime": runtime,
            "policy": policy,
            "threads": threads,
            "interop_threads": 1,
            "batch_size": batch_size,
            "detector_batch_size": 1,
            "precision": "cpu-float32-eager-eval-inference-mode",
            "deterministic_algorithms": True,
            "proposals": "softmax-non-background-max;exclude-N/A;score-desc/index-asc",
            "geometry": "clip-normalized;floor-start-ceil-end;normalize-raster;no-NMS",
            "descriptor": "pinned-BitImageProcessor-center-crop;DINOv2-CLS;float32-L2",
            "source_bounds": "RGB;upright-input;ICC-ignored;numeric-bounds-in-policy",
            "crop_bounds": "RGB;numeric-bounds-in-policy",
            "instance_accuracy_established": False,
        }
        self._model_fingerprint = fingerprint(self._identity)

    def _check_identity(self) -> None:
        if canonical(_implementation_identity()) != self._implementation_snapshot:
            raise ValueError("vision implementation changed after load")
        policy = _policy_identity(self.threads, self.batch_size, self._excluded_classes)
        if canonical(policy) != self._policy_snapshot:
            raise ValueError("vision policy changed after load")
        if canonical(_torch_build_identity()) != self._torch_snapshot:
            raise ValueError("vision Torch runtime changed after load")

    @property
    def identity(self) -> dict[str, JSON]:
        """Return a detached identity after a final source/policy/Torch-setting check."""
        self._check_identity()
        return deepcopy(self._identity)

    @identity.setter
    def identity(self, value: dict[str, JSON]) -> None:
        # Preserve attribute-shaped adapter compatibility; only an identical
        # verified snapshot may be reassigned, never arbitrary report metadata.
        self._check_identity()
        if canonical(value) != canonical(self._identity):
            raise ValueError("cannot replace bound vision identity")

    @property
    def model_fingerprint(self) -> str:
        """Return the bound fingerprint only while sources and policy remain current."""
        self._check_identity()
        return self._model_fingerprint

    @model_fingerprint.setter
    def model_fingerprint(self, value: str) -> None:
        self._check_identity()
        if value != self._model_fingerprint:
            raise ValueError("cannot replace bound vision fingerprint")

    def proposals(self, image: Image.Image) -> tuple[Proposal, ...]:
        """Detect one bounded frame; read last_proposal_counts immediately afterwards."""
        import torch

        self.last_proposal_counts = None
        self._check_identity()
        validate_image(image)
        with torch.inference_mode():
            batch = self.detector_processor(images=[image], return_tensors="pt")
            pixels = batch.get("pixel_values")
            if not isinstance(pixels, torch.Tensor) or pixels.ndim != 4:
                raise ValueError("invalid detector pixels")
            height, width = pixels.shape[2:]
            if not (
                _DETECTOR_MIN_EDGE <= height <= _DETECTOR_MAX_EDGE
                and _DETECTOR_MIN_EDGE <= width <= _DETECTOR_MAX_EDGE
            ):
                raise ValueError("detector preprocessing exceeds bounds")
            pixels = _tensor(pixels, (1, 3, height, width))
            output = self.detector(pixel_values=pixels)
            logits = _tensor(output.logits, (1, _QUERIES, _LABELS + 1))
            boxes = _tensor(output.pred_boxes, (1, _QUERIES, 4))
            # HF YOLOS semantics: softmax includes the final background logit, but
            # argmax considers foreground classes only. Class-index ties use first.
            probabilities = logits.softmax(-1)[0, :, :-1]
            scores, classes = probabilities.max(-1)
            result, counts = _filter_proposals(
                scores.numpy(),
                classes.numpy(),
                boxes[0].numpy(),
                image.size,
                self._excluded_classes,
            )
        self._check_identity()
        self.last_proposal_counts = counts
        return result

    def descriptors(self, images: Sequence[Image.Image]) -> NDArray[np.float32]:
        """Encode exactly one bounded query/crop batch to owned float32 unit rows.

        Empty batches, generators and sequences larger than batch_size are rejected
        BEFORE copying, preprocessing or inference; there is no unbounded encode loop.
        Crops permit 16px edges; validate source/query images with validate_image.
        """
        import torch

        self._check_identity()
        if not isinstance(images, Sequence):
            raise ValueError("descriptor call must contain one bounded nonempty batch")
        count = len(images)
        if not 1 <= count <= self.batch_size:
            raise ValueError("descriptor call must contain one bounded nonempty batch")
        # Index a known, bounded count rather than trusting a custom iterator.
        batch_images = [images[index] for index in range(count)]
        for image in batch_images:
            _validate_image(image, MIN_CROP_EDGE)
        with torch.inference_mode():
            batch = self.descriptor_processor(images=batch_images, return_tensors="pt")
            pixels = _tensor(
                batch.get("pixel_values"),
                (len(batch_images), 3, _DESCRIPTOR_EDGE, _DESCRIPTOR_EDGE),
            )
            output = self.descriptor(pixel_values=pixels)
            hidden = _tensor(
                output.last_hidden_state, (len(batch_images), _DESCRIPTOR_TOKENS, DIMENSION)
            )
            rows = hidden[:, 0, :]
            norms = torch.linalg.vector_norm(rows, dim=1, keepdim=True)
            if not bool(torch.isfinite(norms).all()) or bool((norms <= 0).any()):
                raise ValueError("invalid descriptor norm")
            normalized = _tensor(rows / norms, (len(batch_images), DIMENSION))
            result = np.array(normalized.numpy(), dtype=np.float32, copy=True, order="C")
        if not np.allclose(np.linalg.norm(result, axis=1), 1.0, rtol=_NORM_RTOL, atol=_NORM_ATOL):
            raise ValueError("descriptor normalization failed")
        self._check_identity()
        return result


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pinned experimental vision model artifacts")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("acquire", "verify"):
        subcommand = commands.add_parser(name)
        subcommand.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (
            acquire_models(args.root) if args.command == "acquire" else verify_models(args.root)
        )
    except (OSError, ValueError):
        raise SystemExit("vision model artifact operation failed") from None
    print(canonical(result).decode("ascii"))


if __name__ == "__main__":
    main()
