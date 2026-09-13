"""Closed registry of approved, pinned SigLIP2 checkpoints."""

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from memotrace_ml.common import JSON, object_value, parse_json


@dataclass(frozen=True, slots=True)
class Checkpoint:
    model_id: str
    revision: str
    input_resolution: int
    patch_size: int
    dimension: int
    parameter_count: int
    manifest_resource: str


DEFAULT_CHECKPOINT = Checkpoint(
    model_id="google/siglip2-base-patch16-224",
    revision="75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2",
    input_resolution=224,
    patch_size=16,
    dimension=768,
    parameter_count=375187970,
    manifest_resource="model-manifest.json",
)

_CHECKPOINTS: Mapping[str, Checkpoint] = MappingProxyType(
    {
        checkpoint.model_id: checkpoint
        for checkpoint in (
            DEFAULT_CHECKPOINT,
            Checkpoint(
                model_id="google/siglip2-base-patch16-384",
                revision="f775b65a79762255128c981547af89addcfe0f88",
                input_resolution=384,
                patch_size=16,
                dimension=768,
                parameter_count=375479810,
                manifest_resource="model-manifest-siglip2-base-patch16-384.json",
            ),
            Checkpoint(
                model_id="google/siglip2-so400m-patch16-384",
                revision="dd658faac399427308559e2c3ac1e99cbe43845d",
                input_resolution=384,
                patch_size=16,
                dimension=1152,
                parameter_count=1136039602,
                manifest_resource="model-manifest-siglip2-so400m-patch16-384.json",
            ),
        )
    }
)
APPROVED_MODEL_IDS = tuple(_CHECKPOINTS)


def checkpoint_for_id(model_id: str = DEFAULT_CHECKPOINT.model_id) -> Checkpoint:
    try:
        return _CHECKPOINTS[model_id]
    except KeyError:
        raise ValueError("unapproved model id") from None


def pinned_manifest(model_id: str = DEFAULT_CHECKPOINT.model_id) -> dict[str, JSON]:
    checkpoint = checkpoint_for_id(model_id)
    packaged = files("memotrace_ml").joinpath(checkpoint.manifest_resource)
    if packaged.is_file():
        raw = packaged.read_bytes()
    else:
        raw = (Path(__file__).parent.parent / checkpoint.manifest_resource).read_bytes()
    manifest = object_value(parse_json(raw))
    trusted = {
        "model_id": checkpoint.model_id,
        "revision": checkpoint.revision,
        "parameter_count": checkpoint.parameter_count,
    }
    if any(manifest.get(key) != value for key, value in trusted.items()):
        raise ValueError("approved manifest metadata mismatch")
    return manifest


def checkpoint_for_manifest(manifest: dict[str, JSON]) -> Checkpoint:
    for checkpoint in _CHECKPOINTS.values():
        if manifest == pinned_manifest(checkpoint.model_id):
            return checkpoint
    raise ValueError("model manifest mismatch")
