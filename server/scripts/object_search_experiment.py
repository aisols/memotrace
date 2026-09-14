"""Offline, bounded image-query experiment; deliberately outside production ML identity."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import signal
import stat
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, cast

import numpy as np
from memotrace_ml.artifacts import directory, publish, read_bytes, reader, staging
from memotrace_ml.benchmark import content_corpus, content_judgments, validate_query_profile
from memotrace_ml.checkpoints import DEFAULT_CHECKPOINT, checkpoint_for_manifest
from memotrace_ml.common import JSON, canonical, fingerprint, list_value, object_value, parse_json
from memotrace_ml.identity import implementation_files, numerical_runtime_identity
from memotrace_ml.images import Box, letterbox, preprocessing_version, query_crop, validate_box
from memotrace_ml.model import validate_architecture, verify_model
from memotrace_ml.openimages import CLASS_PROFILE, METADATA, verified_acquisition
from numpy.typing import NDArray
from PIL import Image, ImageOps

from scripts import object_search_core as core
from scripts import object_search_vision as vision

MAX_IMAGES = 100
MAX_QUERIES = 6
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_BUDGET_MS = 3_600_000
MAX_DESCRIPTOR_ROWS = MAX_IMAGES * (vision.MAX_PROPOSALS + 1) + MAX_QUERIES
SCHEMA = "memotrace-object-search-experiment-v1"
SEMANTIC_INPUT_EDGE = DEFAULT_CHECKPOINT.input_resolution
SEMANTIC_PIXEL_DIVISOR = 127.5
SEMANTIC_PIXEL_OFFSET = 1.0
SEMANTIC_NORM_EPS = 1e-12
SEMANTIC_DISTRIBUTIONS = (
    "torch",
    "transformers",
    "tokenizers",
    "numpy",
    "pillow",
    "safetensors",
    "threadpoolctl",
)


def integer(value: JSON, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid bounded integer")
    return value


def identifier(value: JSON) -> str:
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError("invalid identifier")
    core.FrameKey(value, value)
    return value


def fields(value: JSON, expected: set[str]) -> dict[str, JSON]:
    result = object_value(value)
    if set(result) != expected:
        raise ValueError("unexpected or missing manifest fields")
    return result


def external(path: Path, *, file: bool = False) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("explicit absolute external path required")
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise ValueError("artifact must be outside Git")
    with directory(path.parent if file else path):
        pass
    return path


def receipt(body: bytes) -> dict[str, JSON]:
    return {"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}


@dataclass(frozen=True)
class ImageInput:
    id: str
    path: str
    sha256: str
    byte_length: int
    stream: str
    timestamp_ms: int | None
    sequence_id: str

    def public(self) -> dict[str, JSON]:
        return {
            "id": self.id,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "stream": self.stream,
            "timestamp_ms": self.timestamp_ms,
            "sequence_id": self.sequence_id,
        }

    def record(self) -> core.FrameRecord:
        # Untimed images are isolated one-element sets, NEVER temporal observations.
        # 0/1 are internal eligibility sentinels, not acquisition times or invented FPS.
        stream = self.stream if self.timestamp_ms is not None else "untimed:" + self.id
        return core.FrameRecord(
            stream, self.id, self.timestamp_ms or 0, self.sha256, self.sequence_id
        )


def image_input(value: JSON, kind: str) -> ImageInput:
    row = fields(
        value, {"id", "path", "sha256", "byte_length", "stream", "timestamp_ms", "sequence_id"}
    )
    path = row["path"]
    if not isinstance(path, str):
        raise ValueError("invalid relative image path")
    relative = PurePosixPath(path)
    if (
        not path
        or len(path) > 1024
        or relative.is_absolute()
        or ".." in relative.parts
        or str(relative) != path
        or "\\" in path
        or "\0" in path
        or relative.suffix.lower() not in {".jpg", ".jpeg", ".png"}
    ):
        raise ValueError("invalid relative image path")
    digest = row["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("invalid image SHA-256")
    timestamp = row["timestamp_ms"]
    if kind == "frames":
        timestamp = integer(timestamp, core.MAX_EXACT_INTEGER)
    elif timestamp is not None:
        raise ValueError("image diagnostics require explicit null timestamps")
    return ImageInput(
        identifier(row["id"]),
        path,
        digest,
        integer(row["byte_length"], MAX_IMAGE_BYTES, 1),
        identifier(row["stream"]),
        timestamp,
        identifier(row["sequence_id"]),
    )


def verified_bytes(root: Path, image: ImageInput) -> bytes:
    body = read_bytes(root / image.path, MAX_IMAGE_BYTES)
    if receipt(body) != {"sha256": image.sha256, "byte_length": image.byte_length}:
        raise ValueError("image bytes changed or differ from declared identity")
    return body


def load_image(root: Path, image: ImageInput) -> Image.Image:
    body = verified_bytes(root, image)
    with Image.open(io.BytesIO(body), formats=["JPEG", "PNG"]) as source:
        width, height = source.size
        if (
            min(width, height) < vision.MIN_EDGE
            or max(width, height) > vision.MAX_EDGE
            or width * height > vision.MAX_PIXELS
            or getattr(source, "n_frames", 1) != 1
        ):
            raise ValueError("source image exceeds bounded single-image raster")
        source.load()
        result = ImageOps.exif_transpose(source).convert("RGB")
    vision.validate_image(result)
    return result


@dataclass(frozen=True)
class QueryInput:
    id: str
    image: ImageInput
    crop: Box | None
    cutoffs: tuple[core.StreamCutoff, ...]
    tracking_window: tuple[str, ...] | None


@dataclass(frozen=True)
class Dataset:
    root: Path
    kind: str
    images: tuple[ImageInput, ...]
    queries: tuple[QueryInput, ...]
    gaps: tuple[core.CoverageGap, ...]
    identity: dict[str, JSON]

    def verify_images(self) -> None:
        for image in (*self.images, *(query.image for query in self.queries)):
            verified_bytes(self.root, image)


def parse_dataset(root: Path, value: JSON, identity: dict[str, JSON]) -> Dataset:
    doc = fields(value, {"schema", "kind", "candidates", "queries", "coverage_gaps"})
    if type(doc["schema"]) is not int or doc["schema"] != 1:
        raise ValueError("manifest schema must be integer 1")
    kind = doc["kind"]
    if kind not in ("frames", "images"):
        raise ValueError("manifest kind must be frames or images")
    kind = cast(str, kind)
    raw_images, raw_queries = list_value(doc["candidates"]), list_value(doc["queries"])
    if not 1 <= len(raw_images) <= MAX_IMAGES or not 1 <= len(raw_queries) <= MAX_QUERIES:
        raise ValueError("manifest candidate/query bound exceeded")
    if kind == "frames" and len(raw_queries) != 1:
        raise ValueError("frame experiment requires exactly one image query")
    images = tuple(image_input(raw, kind) for raw in raw_images)
    index = {image.id: image for image in images}
    if len(index) != len(images):
        raise ValueError("candidate IDs must be unique")
    times: dict[str, int] = {}
    for image in images:
        if image.timestamp_ms is not None:
            if image.timestamp_ms <= times.get(image.stream, -1):
                raise ValueError("manifest stream order must increase strictly")
            times[image.stream] = image.timestamp_ms
    streams = {image.stream for image in images}
    queries: list[QueryInput] = []
    for raw in raw_queries:
        row = fields(raw, {"id", "image", "crop", "cutoffs", "tracking_window"})
        image = image_input(row["image"], kind)
        if image.id in index and image != index[image.id]:
            raise ValueError("query source identity differs from candidate")
        crop = None
        if row["crop"] is not None:
            crop = validate_box(row["crop"])
        cutoffs: tuple[core.StreamCutoff, ...]
        if kind == "frames":
            values = object_value(row["cutoffs"])
            if set(values) != streams:
                raise ValueError("explicit cutoff required for every candidate stream")
            cutoffs = tuple(
                core.StreamCutoff(name, integer(t, core.MAX_EXACT_INTEGER))
                for name, t in values.items()
            )
        else:
            if row["cutoffs"] is not None:
                raise ValueError("untimed image diagnostics have no cutoff clock")
            cutoffs = tuple(core.StreamCutoff(i.record().stream_id, 1) for i in images)
        window = row["tracking_window"]
        tracking = None
        if window is not None:
            ids = list_value(window)
            if kind != "frames" or not 1 <= len(ids) <= MAX_IMAGES:
                raise ValueError("tracking requires an explicitly bounded timed window")
            tracking = tuple(identifier(i) for i in ids)
            if len(set(tracking)) != len(tracking) or any(i not in index for i in tracking):
                raise ValueError("invalid tracking window membership")
            if tracking != tuple(i.id for i in images if i.id in set(tracking)):
                raise ValueError("tracking window must retain manifest order")
            for stream in streams:
                ordered = [i.id for i in images if i.stream == stream]
                selected = [n for n, i in enumerate(ordered) if i in tracking]
                if selected and (
                    len(selected) > core.MAX_FRAMES_PER_STREAM_WINDOW
                    or selected != list(range(selected[0], selected[-1] + 1))
                ):
                    raise ValueError("tracking window must be consecutive and <=64 per stream")
        queries.append(QueryInput(identifier(row["id"]), image, crop, cutoffs, tracking))
    if len({q.id for q in queries}) != len(queries):
        raise ValueError("query IDs must be unique")
    raw_gaps = list_value(doc["coverage_gaps"])
    if len(raw_gaps) > MAX_IMAGES or (kind == "images" and raw_gaps):
        raise ValueError("invalid coverage gap count or clock")
    gaps: list[core.CoverageGap] = []
    for raw in raw_gaps:
        row = fields(raw, {"stream", "start_ms", "end_ms"})
        gap = core.CoverageGap(
            identifier(row["stream"]),
            integer(row["start_ms"], core.MAX_EXACT_INTEGER),
            integer(row["end_ms"], core.MAX_EXACT_INTEGER),
        )
        if gap.stream_id not in streams or any(
            image.stream == gap.stream_id
            and image.timestamp_ms is not None
            and gap.start_ms < image.timestamp_ms < gap.end_ms
            for image in images
        ):
            raise ValueError("coverage gap conflicts with supplied frames")
        if any(
            g.stream_id == gap.stream_id and g.start_ms < gap.end_ms and g.end_ms > gap.start_ms
            for g in gaps
        ):
            raise ValueError("overlapping coverage gaps")
        gaps.append(gap)
    return Dataset(root, kind, images, tuple(queries), tuple(gaps), identity)


def load_manifest(path: Path) -> Dataset:
    external(path, file=True)
    body = read_bytes(path, MAX_MANIFEST_BYTES)
    return parse_dataset(
        path.parent, parse_json(body, exact_numbers=True), {"manifest": receipt(body)}
    )


class UnsupportedQuery(ValueError):
    """A frozen benchmark query cannot be replaced to fit the experiment's raster bounds."""


def openimages_dataset(root: Path, max_queries: int) -> tuple[Dataset, dict[str, str]]:
    """Query-only GT crops; the returned inference dataset contains NO candidate GT."""
    external(root)
    integer(max_queries, MAX_QUERIES, 1)
    preliminary = object_value(parse_json(read_bytes(root / "manifest.json", MAX_MANIFEST_BYTES)))
    if not 1 <= len(list_value(preliminary.get("items"))) <= MAX_IMAGES:
        raise ValueError("Open Images item budget exceeded")
    for name in ("acquisition.json", "ground-truth.json", "selection.json", "attribution.json"):
        with reader(root / name, MAX_MANIFEST_BYTES):
            pass
    for name in METADATA:
        with reader(root / "metadata" / name, 128 * 1024 * 1024):
            pass
    acquisition, dataset, source_items = verified_acquisition(root)
    items, groups = content_corpus(source_items)
    ground_truth = object_value(
        parse_json(read_bytes(root / "ground-truth.json", MAX_MANIFEST_BYTES), exact_numbers=True)
    )
    classes = object_value(ground_truth["classes"])
    validate_query_profile(classes)
    judged_by_class = {
        mid: content_judgments(groups, object_value(object_value(classes[mid])["judgments"]))
        for _, mid in CLASS_PROFILE
    }
    images = tuple(
        ImageInput(i.id, i.path, i.sha256, i.byte_length, "openimages", None, "independent-image")
        for i in items
    )
    queries: list[QueryInput] = []
    query_classes: dict[str, str] = {}
    selected: list[JSON] = []
    excluded: list[JSON] = []
    # Match benchmark.py's source choice, restricted to its primary both-polarities group.
    for _, mid in CLASS_PROFILE:
        data = object_value(classes[mid])
        judgments = object_value(data["judgments"])
        boxes = object_value(data["boxes"])
        positive_count = sum(value is True for value in judged_by_class[mid].values())
        negative_count = sum(value is False for value in judged_by_class[mid].values())
        boxed = sorted(
            (
                item
                for item in source_items
                if judgments.get(item.id) is True and boxes.get(item.id)
            ),
            key=lambda item: item.id,
        )
        reason = (
            "need_two_unique_positive_contents"
            if positive_count < 2
            else "need_negative_content"
            if not negative_count
            else "no_boxed_positive"
            if not boxed
            else "max_queries"
            if len(queries) == max_queries
            else None
        )
        if reason is not None:
            excluded.append({"class": mid, "reason": reason})
            continue
        item = boxed[0]
        image = ImageInput(
            item.id,
            item.path,
            item.sha256,
            item.byte_length,
            "openimages",
            None,
            "independent-image",
        )
        declared = [object_value(b)["box"] for b in list_value(boxes[item.id])]
        for box in declared:
            validate_box(box)

        def area(box: JSON) -> float:
            # Same float64 area/stable annotation-order tie rule as benchmark.py.
            # Retain the selected exact coordinates for the actual query raster.
            x0, y0, x1, y1 = (float(cast(float, c)) for c in list_value(box))
            return (x1 - x0) * (y1 - y0)

        crop = validate_box(max(declared, key=area))
        with load_image(root, image) as source, query_crop(source, crop) as q:
            if min(q.size) < vision.MIN_EDGE:
                raise UnsupportedQuery(
                    "frozen Open Images primary query crop is below 32px; no alternate selected"
                )
        query_id = mid + ":image"
        queries.append(
            QueryInput(
                query_id,
                image,
                crop,
                tuple(core.StreamCutoff(i.record().stream_id, 1) for i in images),
                None,
            )
        )
        query_classes[query_id] = mid
        signature: dict[str, JSON] = {
            "class": mid,
            "source_id": image.id,
            "source_sha256": image.sha256,
            "box": list(crop),
        }
        selected.append(
            {
                "query_id": query_id,
                "signature": signature,
                "signature_sha256": fingerprint(signature),
            }
        )
    if not queries:
        raise ValueError("no primary both-polarities Open Images image queries")
    identity: dict[str, JSON] = {
        "adapter": "verified-openimages-v3-benchmark-primary-image-cohort-v2",
        "acquisition": acquisition,
        "dataset": dataset,
        "query_selection": (
            "class-profile-order;primary-both-polarities;first-boxed-positive-ID;largest-box"
        ),
        "unsupported_query_policy": "fail-frozen-query;never-select-alternate",
        "query_count_requested": max_queries,
        "selected_queries": selected,
        "selected_query_signatures_sha256": fingerprint(selected),
        "excluded_classes": excluded,
        "content_policy": "SHA256-dedup;smallest-ID-representative;conflicting-labels-fail",
        "source_asset_count": len(source_items),
        "unique_content_count": len(items),
        "content_alias_count": len(source_items) - len(items),
    }
    return Dataset(root, "images", images, tuple(queries), (), identity), query_classes


class SemanticAdapter(Protocol):
    dimension: int

    @property
    def identity(self) -> dict[str, JSON]: ...

    @property
    def model_fingerprint(self) -> str: ...

    def images(self, images: list[Image.Image]) -> list[list[float]]: ...


class VisionAdapter(Protocol):
    identity: dict[str, JSON]
    model_fingerprint: str
    last_proposal_counts: vision.ProposalCounts | None

    def proposals(self, image: Image.Image) -> tuple[vision.Proposal, ...]: ...

    def descriptors(self, images: Sequence[Image.Image]) -> NDArray[np.float32]: ...


def semantic_implementation_identity() -> dict[str, JSON]:
    packaged = implementation_files()
    return {
        "version": "object-experiment-semantic-implementation-v1",
        "object_search_experiment.py": receipt(source_bytes(Path(__file__).absolute())),
        "packaged_implementation_files": packaged,
        "packaged_implementation_sha256": fingerprint(packaged),
    }


def semantic_runtime_settings() -> dict[str, JSON]:
    import torch
    from threadpoolctl import threadpool_info

    pools = [
        {
            key: pool.get(key)
            for key in (
                "user_api",
                "internal_api",
                "prefix",
                "version",
                "num_threads",
                "threading_layer",
                "architecture",
            )
        }
        for pool in threadpool_info()
    ]
    pools.sort(key=lambda pool: canonical(cast(dict[str, JSON], pool)))
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
        "threadpools": cast(list[JSON], pools),
    }


def semantic_policy(threads: int, batch_size: int) -> dict[str, JSON]:
    return {
        "threads": threads,
        "batch_size": batch_size,
        "dimension": DEFAULT_CHECKPOINT.dimension,
        "input_edge": SEMANTIC_INPUT_EDGE,
        "preprocessing_version": preprocessing_version(SEMANTIC_INPUT_EDGE),
        "pixels": "upright-RGB;ICC-ignored;letterbox-bilinear-pad127;CHW",
        "pixel_divisor": SEMANTIC_PIXEL_DIVISOR,
        "pixel_offset": SEMANTIC_PIXEL_OFFSET,
        "l2_dimension": -1,
        "l2_epsilon": SEMANTIC_NORM_EPS,
        "precision": "cpu-float32-eager-eval-inference-mode",
        "query_crop": "exact-decimal-floor-start-ceil-end",
    }


class SemanticModel:
    """Image-only Base224, using the existing full-image letterbox math and exact class."""

    dimension = DEFAULT_CHECKPOINT.dimension

    def __init__(self, root: Path, batch_size: int, threads: int = 4) -> None:
        # VisionModels is loaded first and owns process-wide Torch/threadpool settings.
        import torch
        from transformers import SiglipModel

        integer(threads, 16, 1)
        integer(batch_size, 2, 1)
        self.threads, self.batch_size = threads, batch_size
        implementation = semantic_implementation_identity()
        settings = semantic_runtime_settings()
        if settings["threads"] != threads or settings["interop_threads"] != 1:
            raise ValueError("semantic effective Torch threads differ from requested baseline")
        policy = semantic_policy(threads, batch_size)
        runtime = numerical_runtime_identity(SEMANTIC_DISTRIBUTIONS, settings)
        manifest = verify_model(root)
        if checkpoint_for_manifest(manifest) != DEFAULT_CHECKPOINT:
            raise ValueError("experiment requires verified SigLIP2 Base224")
        model, info = SiglipModel.from_pretrained(
            str(root),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            dtype=torch.float32,
            attn_implementation="eager",
            output_loading_info=True,
            ignore_mismatched_sizes=False,
        )
        if not isinstance(info, dict) or any(
            info.get(key) != []
            for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
        ):
            raise ValueError("SigLIP checkpoint did not load exactly")
        validate_architecture(
            DEFAULT_CHECKPOINT,
            manifest,
            model.config.vision_config.image_size,
            model.config.vision_config.patch_size,
            model.config.vision_config.hidden_size,
            model.config.text_config.max_position_embeddings,
            sum(p.numel() for p in model.parameters()),
        )
        self.model = model.to(device="cpu", dtype=torch.float32).eval()
        if verify_model(root) != manifest:
            raise ValueError("SigLIP artifacts changed during load")
        self._implementation_snapshot = canonical(implementation)
        self._settings_snapshot = canonical(settings)
        self._policy_snapshot = canonical(policy)
        self._identity: dict[str, JSON] = {
            "version": "object-experiment-siglip2-base224-image-only-v2",
            "manifest": manifest,
            "class": "SiglipModel",
            "dimension": self.dimension,
            "implementation": implementation,
            "implementation_sha256": fingerprint(implementation),
            "numerical_runtime": runtime,
            "effective_runtime_settings": settings,
            "policy": policy,
        }
        self._model_fingerprint = fingerprint(self._identity)
        self._check_identity()

    def _check_identity(self) -> None:
        if canonical(semantic_implementation_identity()) != self._implementation_snapshot:
            raise ValueError("semantic implementation changed after load")
        if canonical(semantic_runtime_settings()) != self._settings_snapshot:
            raise ValueError("semantic effective runtime settings changed after load")
        if canonical(semantic_policy(self.threads, self.batch_size)) != self._policy_snapshot:
            raise ValueError("semantic computation policy changed after load")
        if (
            self.model.training
            or str(self.model.dtype) != "torch.float32"
            or str(self.model.device) != "cpu"
            or self.model.config._attn_implementation != "eager"
        ):
            raise ValueError("semantic model precision/device/eval setting changed")

    @property
    def identity(self) -> dict[str, JSON]:
        self._check_identity()
        return deepcopy(self._identity)

    @property
    def model_fingerprint(self) -> str:
        self._check_identity()
        return self._model_fingerprint

    def images(self, images: list[Image.Image]) -> list[list[float]]:
        import torch

        self._check_identity()
        if not 1 <= len(images) <= self.batch_size:
            raise ValueError("invalid semantic batch")
        arrays = []
        for image in images:
            with letterbox(image, SEMANTIC_INPUT_EDGE) as raster:
                arrays.append(
                    np.asarray(raster, dtype=np.float32).transpose(2, 0, 1) / SEMANTIC_PIXEL_DIVISOR
                    - SEMANTIC_PIXEL_OFFSET
                )
        with torch.inference_mode():
            vectors = self.model.get_image_features(pixel_values=torch.from_numpy(np.stack(arrays)))
            vectors = torch.nn.functional.normalize(vectors, dim=-1, eps=SEMANTIC_NORM_EPS)
        self._check_identity()
        return cast(list[list[float]], vectors.tolist())


@dataclass(frozen=True)
class Options:
    top_k: int = 20
    threads: int = 4
    batch_size: int = 2
    max_budget_ms: int = MAX_BUDGET_MS
    max_detector_frames: int = MAX_IMAGES

    def __post_init__(self) -> None:
        integer(self.top_k, MAX_IMAGES, 1)
        if self.threads != 4 or self.batch_size != 2:
            raise ValueError("this narrow baseline requires threads4/batch2")
        integer(self.max_budget_ms, MAX_BUDGET_MS, 1)
        integer(self.max_detector_frames, MAX_IMAGES, 1)


class Runner:
    def __init__(
        self, dataset: Dataset, semantic: SemanticAdapter, detector: VisionAdapter, options: Options
    ) -> None:
        self.dataset, self.semantic, self.detector, self.options = (
            dataset,
            semantic,
            detector,
            options,
        )
        self.started = time.monotonic()
        self.cache: dict[str, core.FrameCrops] = {}
        self.evidence: dict[str, JSON] = {}
        self.work = {
            "semantic_images": 0,
            "semantic_batches": 0,
            "detector_frames": 0,
            "descriptor_rows": 0,
            "descriptor_batches": 0,
            "proposal_cache_hits": 0,
        }
        self.timers = {
            "semantic_seconds": 0.0,
            "detector_seconds": 0.0,
            "descriptor_seconds": 0.0,
            "ranking_tracking_seconds": 0.0,
        }

    def check_budget(self) -> None:
        if (time.monotonic() - self.started) * 1000 >= self.options.max_budget_ms:
            raise ValueError("experiment wall-clock budget exhausted")

    def semantic_batch(self, images: list[Image.Image]) -> tuple[core.UnitVector, ...]:
        self.check_budget()
        start = time.monotonic()
        rows = np.asarray(self.semantic.images(images), dtype=np.float32)
        if rows.shape != (len(images), self.semantic.dimension):
            raise ValueError("invalid semantic adapter shape")
        vectors = tuple(core.UnitVector.from_array(row) for row in rows)
        self.work["semantic_images"] += len(images)
        self.work["semantic_batches"] += 1
        self.timers["semantic_seconds"] += time.monotonic() - start
        return vectors

    def descriptors(self, images: list[Image.Image]) -> core.UnitMatrix:
        self.check_budget()
        if self.work["descriptor_rows"] + len(images) > MAX_DESCRIPTOR_ROWS:
            raise ValueError("descriptor work budget exhausted")
        start = time.monotonic()
        rows = self.detector.descriptors(images)
        if rows.shape != (len(images), vision.DIMENSION):
            raise ValueError("invalid instance descriptor shape")
        matrix = core.UnitMatrix.from_array(rows)
        self.work["descriptor_rows"] += len(images)
        self.work["descriptor_batches"] += 1
        self.timers["descriptor_seconds"] += time.monotonic() - start
        return matrix

    def crops(self, image: ImageInput) -> core.FrameCrops:
        if image.id in self.cache:
            self.work["proposal_cache_hits"] += 1
            return self.cache[image.id]
        self.check_budget()
        if len(self.cache) >= self.options.max_detector_frames:
            raise ValueError("shared detector frame budget exhausted")
        with load_image(self.dataset.root, image) as source:
            start = time.monotonic()
            proposals = self.detector.proposals(source)
            counts = self.detector.last_proposal_counts
            if counts is None or counts.returned != len(proposals) or len(proposals) > 20:
                raise ValueError("invalid detector proposal accounting")
            self.timers["detector_seconds"] += time.monotonic() - start
            self.work["detector_frames"] += 1
            regions: Sequence[vision.Proposal | vision.FullImageFallback] = (
                proposals if proposals else (vision.full_image_fallback(source),)
            )
            vectors: list[core.UnitMatrix] = []
            for offset in range(0, len(regions), self.options.batch_size):
                crops = [r.crop(source) for r in regions[offset : offset + self.options.batch_size]]
                try:
                    vectors.append(self.descriptors(crops))
                finally:
                    for crop in crops:
                        crop.close()
            matrix = core.UnitMatrix.from_array(np.concatenate([v.array() for v in vectors]))
        record = image.record()
        observations = tuple(
            core.Observation(
                record.stream_id,
                record.frame_id,
                record.timestamp_ms,
                ordinal,
                proposal.class_id,
                core.NormalizedBox(*proposal.box),
            )
            for ordinal, proposal in enumerate(proposals)
        )
        result = core.FrameCrops(
            record,
            self.detector.model_fingerprint,
            matrix if proposals else core.UnitMatrix(b"", 0, vision.DIMENSION),
            observations,
            core.UnitVector.from_array(matrix.array()[0]) if not proposals else None,
        )
        self.cache[image.id] = result
        self.evidence[image.id] = {
            "counts": cast(dict[str, JSON], asdict(counts)),
            "proposals": [
                {
                    "ordinal": ordinal,
                    "box": list(p.box),
                    "pixel_box": list(p.pixel_box),
                    "score": p.score,
                    "class_id": p.class_id,
                    "query_index": p.query_index,
                }
                for ordinal, p in enumerate(proposals)
            ],
            "full_image_fallback": not proposals,
        }
        return result

    def history(self, query: QueryInput, result: core.SearchResult) -> dict[str, JSON]:
        if self.dataset.kind == "images":
            return {
                "status": "unknown_time_no_temporal_tracking",
                "tracklets": [],
                "detector_temporal_coverage": "unknown",
                "unknown_gaps": [],
            }
        cutoffs = {c.stream_id: c.timestamp_ms for c in query.cutoffs}
        seeds = {
            h.best_match.observation.key
            for h in result.proposals_only_ranking
            if h.best_match is not None and h.best_match.observation is not None
        }
        window = query.tracking_window
        tracklets: list[core.Tracklet] = []
        gaps: list[JSON] = []
        observed_ids: list[str] = []
        excluded_ids: list[str] = []
        if window is None:
            # Do not turn a relevance-ordered sparse shortlist into observed tracking.
            for crop in result.crops:
                start = time.monotonic()
                single = core.associate_tracklets(result.semantic.query, (crop,))
                self.timers["ranking_tracking_seconds"] += time.monotonic() - start
                tracklets.extend(single.tracklets)
            previous: dict[str, int] = {}
            for image in self.dataset.images:
                timestamp = image.timestamp_ms
                if timestamp is None or timestamp >= cutoffs[image.stream]:
                    continue
                if image.stream in previous:
                    gaps.append(
                        {
                            "stream": image.stream,
                            "start_ms": previous[image.stream],
                            "end_ms": timestamp,
                            "reason": "no_chronological_detector_window",
                        }
                    )
                previous[image.stream] = timestamp
            status = "shortlist_singletons_only_chronological_coverage_unknown"
        else:
            selected: list[core.FrameCrops] = []
            for image in self.dataset.images:
                if image.id not in window or image.record().timestamp_ms >= cutoffs[image.stream]:
                    continue
                if image.id == query.image.id or image.sha256 == query.image.sha256:
                    excluded_ids.append(image.id)
                    selected.append(
                        core.FrameCrops(
                            image.record(),
                            self.detector.model_fingerprint,
                            core.UnitMatrix(b"", 0, vision.DIMENSION),
                            (),
                        )
                    )
                else:
                    observed_ids.append(image.id)
                    selected.append(self.crops(image))
            start = time.monotonic()
            tracked = core.validate_tracklet_result(
                core.associate_tracklets(result.semantic.query, tuple(selected), self.dataset.gaps)
            )
            self.timers["ranking_tracking_seconds"] += time.monotonic() - start
            tracklets.extend(tracked.tracklets)
            gaps = [
                {
                    "stream": g.stream_id,
                    "start_ms": g.start_ms,
                    "end_ms": g.end_ms,
                    "reason": g.reason.value,
                }
                for g in tracked.unknown_gaps
            ]
            status = "bounded_chronological_window_proposal_associations"
        return {
            "status": status,
            "detector_temporal_coverage": "explicit_window_only" if window else "unknown",
            "observed_frame_ids": [*observed_ids],
            "excluded_frame_ids": [*excluded_ids],
            "unknown_gaps": gaps,
            "declared_coverage_gaps": [
                {
                    "stream": g.stream_id,
                    "start_ms": g.start_ms,
                    "end_ms": min(g.end_ms, cutoffs[g.stream_id]),
                }
                for g in self.dataset.gaps
                if g.start_ms < cutoffs[g.stream_id]
            ],
            "tracklets": [
                {
                    "stream": t.stream_id,
                    "sequence_id": t.sequence_id,
                    "first_observed_timestamp_ms": t.first_observed_timestamp_ms,
                    "last_observed_timestamp_ms": t.last_observed_timestamp_ms,
                    "observations": [
                        {
                            "frame_id": o.frame_id,
                            "region_ordinal": o.region_ordinal,
                            "timestamp_ms": o.timestamp_ms,
                            "box": list(asdict(o.box).values()),
                        }
                        for o in t.observations
                    ],
                    "links": [
                        {
                            "previous_frame_id": link.previous.frame_id,
                            "current_frame_id": link.current.frame_id,
                            "cosine": link.cosine,
                            "iou": link.iou,
                            "joint_score": link.joint_score,
                        }
                        for link in t.links
                    ],
                }
                for t in tracklets
                if any(o.key in seeds for o in t.observations)
            ],
        }

    def run(self) -> dict[str, JSON]:
        self.dataset.verify_images()
        semantic: list[core.SemanticFrame] = []
        for offset in range(0, len(self.dataset.images), self.options.batch_size):
            inputs = self.dataset.images[offset : offset + self.options.batch_size]
            images: list[Image.Image] = []
            try:
                for image in inputs:
                    images.append(load_image(self.dataset.root, image))
                vectors = self.semantic_batch(images)
                semantic.extend(
                    core.SemanticFrame(i.record(), self.semantic.model_fingerprint, v)
                    for i, v in zip(inputs, vectors, strict=True)
                )
            finally:
                for raster in images:
                    raster.close()
        queries: list[JSON] = []
        by_id = {image.id: image for image in self.dataset.images}
        for query in self.dataset.queries:
            before = self.work.copy()
            timers_before = self.timers.copy()
            with load_image(self.dataset.root, query.image) as image:
                crop = query_crop(image, query.crop) if query.crop is not None else image.copy()
                with crop:
                    vision.validate_image(crop)
                    q_semantic = self.semantic_batch([crop])[0]
                    q_instance = self.descriptors([crop])
            search = core.SearchQuery(
                query.id,
                query.image.record().key,
                query.image.sha256,
                query.cutoffs,
                self.semantic.model_fingerprint,
                q_semantic,
                self.detector.model_fingerprint,
                q_instance,
            )
            start = time.monotonic()
            ranking = core.rank_semantic(search, tuple(semantic))
            self.timers["ranking_tracking_seconds"] += time.monotonic() - start
            crops = tuple(
                self.crops(by_id[h.frame.frame_id])
                for h in ranking.full_ranking[: self.options.top_k]
            )
            start = time.monotonic()
            result = core.validate_search_result(
                core.rerank_shortlist(ranking, crops, self.options.top_k)
            )
            self.timers["ranking_tracking_seconds"] += time.monotonic() - start
            history = self.history(query, result)
            source_excluded = [
                i.id
                for i in self.dataset.images
                if i.id == query.image.id or i.sha256 == query.image.sha256
            ]
            queries.append(
                {
                    "query_id": query.id,
                    "source": query.image.public(),
                    "crop": list(query.crop) if query.crop is not None else None,
                    "cutoffs": (
                        {c.stream_id: c.timestamp_ms for c in query.cutoffs}
                        if self.dataset.kind == "frames"
                        else None
                    ),
                    "source_exclusion": {
                        "policy": "source-id-and-exact-source-byte-sha256",
                        "excluded_ids": [*source_excluded],
                    },
                    "shortlist": [key.frame_id for key in result.shortlist],
                    "baseline": [
                        {"id": h.frame.frame_id, "semantic_cosine": h.semantic_cosine}
                        for h in ranking.full_ranking
                    ],
                    "reranked": [hit_json(h) for h in result.staged_ranking],
                    "history": history,
                    "work": {key: value - before[key] for key, value in self.work.items()},
                    "timers": {
                        key: value - timers_before[key] for key, value in self.timers.items()
                    },
                }
            )
        self.check_budget()
        return {
            "schema": SCHEMA,
            "experimental": True,
            "quality_claim": "unvalidated appearance experiment; no same-instance quality claim",
            "dataset": self.dataset.identity,
            "kind": self.dataset.kind,
            "inputs": [i.public() for i in self.dataset.images],
            "options": cast(dict[str, JSON], asdict(self.options)),
            "semantic_identity": self.semantic.identity,
            "semantic_space": self.semantic.model_fingerprint,
            "descriptor_identity": self.detector.identity,
            "descriptor_space": self.detector.model_fingerprint,
            "ranking_policy": "full-semantic-topK;independent-DINO-max;unchanged-semantic-tail",
            "fallback_policy": "DINO-full-image-if-zero-YOLOS-proposals;never-an-observation",
            "queries": queries,
            "proposal_evidence": self.evidence,
            "work": dict(self.work),
            "timers": dict(self.timers),
            "cache": {
                "semantic_vectors": len(semantic),
                "proposal_frames": len(self.cache),
                "descriptor_elements": sum(
                    (c.vectors.rows + int(c.fallback is not None)) * vision.DIMENSION
                    for c in self.cache.values()
                ),
                "max_descriptor_elements": MAX_IMAGES * 21 * vision.DIMENSION,
            },
        }


def hit_json(hit: core.SemanticHit | core.InstanceHit) -> dict[str, JSON]:
    if isinstance(hit, core.SemanticHit):
        return {
            "id": hit.frame.frame_id,
            "semantic_cosine": hit.semantic_cosine,
            "instance_cosine": None,
            "evidence": "semantic_tail",
        }
    match = hit.best_match
    return {
        "id": hit.frame.frame_id,
        "semantic_cosine": hit.semantic.semantic_cosine,
        "instance_cosine": hit.instance_cosine,
        "evidence": match.kind.value if match else "no_evidence",
        "proposal_ordinal": (
            match.observation.region_ordinal if match and match.observation else None
        ),
    }


def class_metrics(order: list[str], judgments: dict[str, JSON], k: int) -> dict[str, JSON]:
    if len(set(order)) != len(order):
        raise ValueError("duplicate candidate in class metric ranking")
    labels = [judgments.get(i) for i in order]
    if any(value is not None and type(value) is not bool for value in labels):
        raise ValueError("invalid class-level judgment")
    judged = [value for value in labels if value is not None]
    positives = sum(value is True for value in judged)
    negatives = sum(value is False for value in judged)
    found = 0
    precision_sum = 0.0
    for rank, value in enumerate(judged, 1):
        if value is True:
            found += 1
            precision_sum += found / rank
    hits = sum(value is True for value in judged[:k])
    return {
        "AP": precision_sum / positives if positives else None,
        "Hit@K": int(hits > 0) if positives else None,
        "Recall@K": hits / positives if positives else None,
        "unknown@K": sum(value is None for value in labels[:k]),
        "judged_candidates": len(judged),
        "positive_candidates": positives,
        "negative_candidates": negatives,
        "primary_eligible": bool(positives and negatives),
    }


def join_openimages_metrics(
    report: dict[str, JSON], root: Path, query_classes: dict[str, str], k: int
) -> None:
    # Called only AFTER all blind rankings and proposal inference have completed.
    truth = object_value(parse_json(read_bytes(root / "ground-truth.json", MAX_MANIFEST_BYTES)))
    classes = object_value(truth["classes"])
    _, _, source_items = verified_acquisition(root)
    items, groups = content_corpus(source_items)
    if [object_value(raw)["id"] for raw in list_value(report["inputs"])] != [i.id for i in items]:
        raise ValueError("metric corpus differs from blind content representatives")
    selected = {
        cast(str, object_value(raw)["query_id"]): object_value(raw)
        for raw in list_value(object_value(report["dataset"])["selected_queries"])
    }
    sums: dict[str, dict[str, list[float]]] = {
        name: {metric: [] for metric in ("AP", "Hit@K", "Recall@K")}
        for name in ("baseline", "reranked")
    }
    excluded: dict[str, list[JSON]] = {name: [] for name in sums}
    for raw in list_value(report["queries"]):
        query = object_value(raw)
        query_id = cast(str, query["query_id"])
        mid = query_classes[query_id]
        judgments = content_judgments(groups, object_value(object_value(classes[mid])["judgments"]))
        source_hash = cast(str, object_value(query["source"])["sha256"])
        expected_ids = {i.id for i in items if i.sha256 != source_hash}
        signature: dict[str, JSON] = {
            "class": mid,
            "source_id": object_value(query["source"])["id"],
            "source_sha256": source_hash,
            "box": query["crop"],
        }
        if canonical(signature) != canonical(selected[query_id]["signature"]):
            raise ValueError("query differs from frozen primary signature")
        query["query_signature"] = signature
        query["query_signature_sha256"] = fingerprint(signature)
        object_value(query["source_exclusion"])["source_alias_ids"] = [
            i.id for i in groups[source_hash]
        ]
        metrics: dict[str, JSON] = {
            "class_id": mid,
            "diagnostic": "class-proxy-not-same-instance",
            "primary_eligibility": "both_polarities_after_source_content_exclusion",
        }
        for name in sums:
            order = [cast(str, object_value(hit)["id"]) for hit in list_value(query[name])]
            if set(order) != expected_ids:
                raise ValueError("metric ranking differs from eligible unique-content corpus")
            values = class_metrics(order, judgments, k)
            metrics[name] = values
            if values["primary_eligible"]:
                for metric in sums[name]:
                    sums[name][metric].append(float(cast(float, values[metric])))
            else:
                excluded[name].append(
                    {
                        "query_id": query_id,
                        "reason": "no_positive"
                        if not values["positive_candidates"]
                        else "no_negative",
                    }
                )
        query["class_metrics"] = metrics
    report["class_metrics"] = {
        "scope": "frozen-primary-image-queries-class-level-diagnostic-not-same-instance",
        "unknown_policy": "removed-only-from-metric-order;unknown@K-counts-original-topK",
        "eligibility": "both_polarities_after_source_content_exclusion",
        "content_policy": "benchmark-content_corpus-and-content_judgments",
        "K": k,
        "mAP": {
            name: sum(values["AP"]) / len(values["AP"]) if values["AP"] else None
            for name, values in sums.items()
        },
        "Hit@K": {
            name: sum(values["Hit@K"]) / len(values["Hit@K"]) if values["Hit@K"] else None
            for name, values in sums.items()
        },
        "Recall@K": {
            name: sum(values["Recall@K"]) / len(values["Recall@K"]) if values["Recall@K"] else None
            for name, values in sums.items()
        },
        "eligible_queries": {name: len(values["AP"]) for name, values in sums.items()},
        "excluded_queries": {name: values for name, values in excluded.items()},
        "comparison": "fresh baseline and rerank from this run;no historic metrics reused",
    }


def source_bytes(path: Path) -> bytes:
    """Source trees need not use artifact ownership modes; still forbid symlink traversal."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        source_fd = os.open(path.name, flags | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(source_fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:
            raise ValueError("source must be a bounded regular file")
        body = source.read(MAX_MANIFEST_BYTES + 1)
        if len(body) != info.st_size:
            raise ValueError("source changed while reading")
        return body


def source_identity() -> dict[str, JSON]:
    root = Path(__file__).absolute().parent
    return {
        "scripts": {
            name: receipt(source_bytes(root / name))
            for name in (
                "object_search_experiment.py",
                "object_search_core.py",
                "object_search_vision.py",
            )
        },
        "ml_implementation": implementation_files(),
        "python": platform.python_version(),
    }


@contextmanager
def deadline(milliseconds: int) -> Iterator[None]:
    def expired(signum: int, frame: object) -> None:
        raise TimeoutError("experiment wall-clock budget exhausted")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, milliseconds / 1000)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def write_report(output: Path, report: dict[str, JSON], recheck: Callable[[], None]) -> None:
    external(output, file=True)
    recheck()
    body = canonical(report) + b"\n"
    if len(body) > MAX_REPORT_BYTES:
        raise ValueError("report size budget exceeded")
    with staging(output) as (fd, parent, name):
        with os.fdopen(os.dup(fd), "wb") as target:
            target.write(body)
        publish(fd, parent, name, output.name)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("manifest", "openimages"):
        sub = commands.add_parser(name)
        sub.add_argument("--model-dir", type=Path, required=True)
        sub.add_argument("--vision-root", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        sub.add_argument("--top-k", type=int, default=20)
        sub.add_argument("--threads", type=int, default=4)
        sub.add_argument("--batch-size", type=int, default=2)
        sub.add_argument("--max-budget-ms", type=int, default=MAX_BUDGET_MS)
        sub.add_argument("--max-detector-frames", type=int, default=MAX_IMAGES)
        if name == "manifest":
            sub.add_argument("--manifest", type=Path, required=True)
        else:
            sub.add_argument("--data-root", type=Path, required=True)
            sub.add_argument("--max-queries", type=int, default=MAX_QUERIES)
    args = parser.parse_args(argv)
    try:
        options = Options(
            args.top_k, args.threads, args.batch_size, args.max_budget_ms, args.max_detector_frames
        )
        with deadline(options.max_budget_ms):
            started = time.monotonic()
            external(args.output, file=True)
            if args.output.exists() or args.output.is_symlink():
                raise ValueError("output must be a new exclusive file")
            external(args.model_dir)
            external(args.vision_root)
            sources = source_identity()
            model_identity = verify_model(args.model_dir)
            if checkpoint_for_manifest(model_identity) != DEFAULT_CHECKPOINT:
                raise ValueError("experiment requires SigLIP2 Base224")
            vision_identity = vision.verify_models(args.vision_root)
            query_classes: dict[str, str] = {}
            if args.command == "manifest":
                dataset = load_manifest(args.manifest)
            else:
                dataset, query_classes = openimages_dataset(args.data_root, args.max_queries)
            dataset.verify_images()
            load_started = time.monotonic()
            models = vision.VisionModels(args.vision_root, threads=4, batch_size=2)
            semantic = SemanticModel(args.model_dir, batch_size=2)
            load_seconds = time.monotonic() - load_started
            report = Runner(dataset, semantic, models, options).run()
            report["implementation"] = sources
            report["model_load_seconds"] = load_seconds
            if query_classes:
                join_openimages_metrics(report, args.data_root, query_classes, options.top_k)

            def recheck() -> None:
                if source_identity() != sources or verify_model(args.model_dir) != model_identity:
                    raise ValueError("source or semantic model identity changed")
                if vision.verify_models(args.vision_root) != vision_identity:
                    raise ValueError("vision model identity changed")
                if (
                    semantic.identity != report["semantic_identity"]
                    or semantic.model_fingerprint != report["semantic_space"]
                ):
                    raise ValueError("semantic computation identity changed")
                if (
                    models.identity != report["descriptor_identity"]
                    or models.model_fingerprint != report["descriptor_space"]
                ):
                    raise ValueError("vision computation identity changed")
                if args.command == "manifest":
                    if load_manifest(args.manifest) != dataset:
                        raise ValueError("input manifest changed")
                else:
                    fresh, fresh_classes = openimages_dataset(args.data_root, args.max_queries)
                    if fresh != dataset or fresh_classes != query_classes:
                        raise ValueError("Open Images acquisition/query identity changed")
                dataset.verify_images()
                report["total_seconds_before_publication"] = time.monotonic() - started

            # Recheck immediately before serialization and exclusive atomic publication.
            write_report(args.output, report, recheck)
    except UnsupportedQuery as error:
        raise SystemExit(str(error)) from None
    except (OSError, ValueError, TimeoutError):
        raise SystemExit(
            "object-search experiment failed validation, bounds, or artifact I/O"
        ) from None
    print("object-search experiment report published")


if __name__ == "__main__":
    main()
