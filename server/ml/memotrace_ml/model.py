"""Verified local SigLIP2 weights, CPU float32 only; no orchestration or fallback."""

import hashlib
import os
import time
from pathlib import Path
from typing import Protocol, cast

import numpy as np
from PIL import Image

from memotrace_ml.artifacts import entries, reader
from memotrace_ml.checkpoints import Checkpoint, checkpoint_for_manifest
from memotrace_ml.common import (
    JSON,
    object_value,
    read_json,
    string_value,
)
from memotrace_ml.identity import fingerprint_with_implementation, numerical_runtime_identity
from memotrace_ml.images import letterbox, preprocessing_version


class Encoder(Protocol):
    model_fingerprint: str
    dimension: int
    model_id: str
    model_revision: str
    input_resolution: int
    preprocessing_version: str

    def images(self, images: list[Image.Image]) -> list[list[float]]: ...

    def text(self, text: str) -> list[float]: ...


class UnsupportedText(ValueError):
    """The tokenizer cannot represent otherwise valid public query text."""


def verify_model(root: Path) -> dict[str, JSON]:
    manifest = read_json(root / "manifest.json")
    checkpoint_for_manifest(manifest)
    files = object_value(manifest["files"])
    if set(entries(root)) != {*files, "manifest.json"}:
        raise ValueError("unexpected model artifact")
    for name, value in files.items():
        path = root / name
        meta = object_value(value)
        with reader(path) as source:
            if os.fstat(source.fileno()).st_size != meta["byte_length"]:
                raise ValueError("model size mismatch")
            if hashlib.file_digest(source, "sha256").hexdigest() != meta["sha256"]:
                raise ValueError("model digest mismatch")
    return manifest


def validate_architecture(
    checkpoint: Checkpoint,
    manifest: dict[str, JSON],
    image_size: object,
    patch_size: object,
    dimension: object,
    max_tokens: object,
    parameter_count: object,
) -> None:
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (image_size, patch_size, dimension, max_tokens, parameter_count)
        )
        or image_size != checkpoint.input_resolution
        or patch_size != checkpoint.patch_size
        or dimension != checkpoint.dimension
        or max_tokens != 64
        or parameter_count != checkpoint.parameter_count
        or parameter_count != manifest["parameter_count"]
    ):
        raise ValueError("unexpected architecture")


def validate_runtime_bounds(threads: int, batch_size: int) -> None:
    if (
        isinstance(threads, bool)
        or isinstance(batch_size, bool)
        or not 1 <= threads <= 16
        or not 1 <= batch_size <= 8
    ):
        raise ValueError("invalid runtime bounds")


class SiglipEncoder:
    def __init__(self, model_dir: Path, threads: int = 4, batch_size: int = 2) -> None:
        started = time.monotonic()
        validate_runtime_bounds(threads, batch_size)
        manifest = verify_model(model_dir)
        checkpoint = checkpoint_for_manifest(manifest)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        import torch
        from threadpoolctl import threadpool_limits
        from transformers import AutoTokenizer, SiglipModel
        from transformers.utils import logging

        logging.set_verbosity_error()  # type: ignore[no-untyped-call]
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        # Also bound NumPy's BLAS pool; torch.set_num_threads alone does not cover it.
        self._thread_limiter = threadpool_limits(limits=threads)
        self.batch_size = batch_size
        self.threads = threads
        self.model_id = string_value(manifest["model_id"])
        self.model_revision = string_value(manifest["revision"])
        self.input_resolution = checkpoint.input_resolution
        self.preprocessing_version = preprocessing_version(self.input_resolution)
        self.tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            str(model_dir), local_files_only=True, trust_remote_code=False, use_fast=True
        )
        self.model = (
            SiglipModel.from_pretrained(
                str(model_dir),
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
                torch_dtype=torch.float32,
                attn_implementation="eager",
            )
            .to("cpu")
            .eval()
        )
        dimension = self.model.config.vision_config.hidden_size
        max_tokens = self.model.config.text_config.max_position_embeddings
        self.parameter_count = sum(p.numel() for p in self.model.parameters())
        validate_architecture(
            checkpoint,
            manifest,
            self.model.config.vision_config.image_size,
            self.model.config.vision_config.patch_size,
            dimension,
            max_tokens,
            self.parameter_count,
        )
        self.dimension = int(dimension)
        self.max_tokens = int(max_tokens)
        # Recheck after path-based third-party loading. A different-UID replacement
        # cannot pass the trusted descriptor checks; a same-UID race remains inside
        # the explicitly documented non-sandbox trust boundary.
        if verify_model(model_dir) != manifest:
            raise ValueError("model changed while loading")
        runtime = numerical_runtime_identity(
            (
                "torch",
                "transformers",
                "tokenizers",
                "numpy",
                "pillow",
                "safetensors",
                "threadpoolctl",
            ),
            {
                "version": str(torch.__version__),
                "git_version": str(torch.version.git_version),
                "debug": bool(torch.version.debug),
                "cpu_capability": str(torch.backends.cpu.get_cpu_capability()),
                "mkldnn": bool(torch.backends.mkldnn.is_available()),  # type: ignore[no-untyped-call]
                "openmp": bool(torch.backends.openmp.is_available()),  # type: ignore[no-untyped-call]
                "cxx11_abi": bool(torch.compiled_with_cxx11_abi()),
            },
        )
        self.identity: dict[str, JSON] = {
            "version": "siglip2-cpu-v4",
            "manifest": manifest,
            "input_resolution": self.input_resolution,
            "preprocessing_version": self.preprocessing_version,
            "image_normalization": "float32-RGB/127.5-1;CHW;ICC-ignored",
            "resize": (
                f"{self.input_resolution}-longest;round-half-up;center-floor;"
                "pad127;bilinear;no-center-crop"
            ),
            "text": "unmodified;specials-and-unk-rejected;max64-eos;pad-max;no-truncation",
            "query_box": "display-normalized;exact-decimal-floor-start-ceil-end-v2",
            "numerical_runtime": runtime,
            "precision": "cpu-float32-eager-l2",
            "threads": threads,
            "interop_threads": 1,
            "blas_threads": threads,
            "batch_size": batch_size,
            "deterministic_algorithms": True,
        }
        self.identity, self.model_fingerprint = fingerprint_with_implementation(self.identity)
        self.load_seconds = time.monotonic() - started

    def images(self, images: list[Image.Image]) -> list[list[float]]:
        import torch

        result: list[list[float]] = []
        with torch.inference_mode():
            for offset in range(0, len(images), self.batch_size):
                arrays = [
                    np.asarray(letterbox(image, self.input_resolution), dtype=np.float32).transpose(
                        2, 0, 1
                    )
                    / 127.5
                    - 1
                    for image in images[offset : offset + self.batch_size]
                ]
                pixels = torch.from_numpy(np.stack(arrays))
                vectors = self.model.get_image_features(pixel_values=pixels)
                vectors = torch.nn.functional.normalize(vectors, dim=-1)
                result.extend(cast(list[list[float]], vectors.tolist()))
        return result

    def text(self, text: str) -> list[float]:
        import torch

        if not text.strip() or len(text) > 2048:
            raise UnsupportedText("invalid text")
        if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in text):
            raise UnsupportedText("unsupported text")
        if any(token in text for token in self.tokenizer.all_special_tokens):
            raise UnsupportedText("unsupported special token")
        ids = self.tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"]
        if len(ids) > self.max_tokens or self.tokenizer.unk_token_id in ids:
            raise UnsupportedText("unsupported or overlong text tokens")
        tokens = self.tokenizer(
            text,
            padding="max_length",
            max_length=self.max_tokens,
            truncation=False,
            return_tensors="pt",
        )
        with torch.inference_mode():
            vector = self.model.get_text_features(input_ids=tokens["input_ids"])
            vector = torch.nn.functional.normalize(vector, dim=-1)
        return cast(list[float], vector[0].tolist())
