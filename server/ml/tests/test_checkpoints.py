"""Approved checkpoint selection is closed, exact, and model-free."""

from collections.abc import Callable
from pathlib import Path

import pytest

from memotrace_ml import acquire
from memotrace_ml.acquire import DownloadReceipt
from memotrace_ml.checkpoints import (
    APPROVED_MODEL_IDS,
    DEFAULT_CHECKPOINT,
    Checkpoint,
    checkpoint_for_id,
    checkpoint_for_manifest,
    pinned_manifest,
)
from memotrace_ml.common import JSON, fingerprint, object_value, read_json, write_json
from memotrace_ml.images import preprocessing_version
from memotrace_ml.model import validate_architecture, verify_model
from memotrace_ml.public_download import MAX_PUBLIC_ARTIFACT_BYTES

EXPECTED = {
    "google/siglip2-base-patch16-224": (
        "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2",
        224,
        768,
        375187970,
    ),
    "google/siglip2-base-patch16-384": (
        "f775b65a79762255128c981547af89addcfe0f88",
        384,
        768,
        375479810,
    ),
    "google/siglip2-so400m-patch16-384": (
        "dd658faac399427308559e2c3ac1e99cbe43845d",
        384,
        1152,
        1136039602,
    ),
}
ARTIFACTS = {
    "README.md",
    "config.json",
    "model.safetensors",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
}


def test_registry_and_manifests_are_exact_and_architecturally_distinct() -> None:
    assert APPROVED_MODEL_IDS == tuple(EXPECTED)
    identities: set[str] = set()
    largest_artifact = 0
    for model_id, (revision, resolution, dimension, parameter_count) in EXPECTED.items():
        checkpoint = checkpoint_for_id(model_id)
        assert checkpoint == Checkpoint(
            model_id,
            revision,
            resolution,
            16,
            dimension,
            parameter_count,
            checkpoint.manifest_resource,
        )
        manifest = pinned_manifest(model_id)
        assert manifest["model_id"] == model_id
        assert manifest["revision"] == revision
        assert manifest["parameter_count"] == parameter_count
        files = object_value(manifest["files"])
        assert set(files) == ARTIFACTS
        for artifact in files.values():
            byte_length = object_value(artifact)["byte_length"]
            assert (
                isinstance(byte_length, int)
                and not isinstance(byte_length, bool)
                and 0 < byte_length <= MAX_PUBLIC_ARTIFACT_BYTES
            )
            largest_artifact = max(largest_artifact, byte_length)
        assert checkpoint_for_manifest(manifest) == checkpoint
        validate_architecture(
            checkpoint,
            manifest,
            resolution,
            16,
            dimension,
            64,
            parameter_count,
        )
        identity: dict[str, JSON] = {
            "manifest": manifest,
            "input_resolution": resolution,
            "preprocessing_version": preprocessing_version(resolution),
        }
        identities.add(fingerprint(identity))
    assert len(identities) == 3
    assert largest_artifact == MAX_PUBLIC_ARTIFACT_BYTES
    assert preprocessing_version(224) != preprocessing_version(384)


def test_unknown_id_and_nonexact_local_manifest_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unapproved"):
        checkpoint_for_id("local/arbitrary-model")
    changed = pinned_manifest()
    changed["revision"] = "0" * 40
    with pytest.raises(ValueError, match="manifest mismatch"):
        checkpoint_for_manifest(changed)
    write_json(tmp_path / "manifest.json", changed)
    with pytest.raises(ValueError, match="manifest mismatch"):
        verify_model(tmp_path)


@pytest.mark.parametrize(
    "architecture",
    [
        (384, 16, 768, 64, 375187970),
        (224, 14, 768, 64, 375187970),
        (224, 16, 1152, 64, 375187970),
        (224, 16, 768, 63, 375187970),
        (224, 16, 768, 64, 375187971),
    ],
)
def test_architecture_drift_fails_closed(architecture: tuple[int, int, int, int, int]) -> None:
    with pytest.raises(ValueError, match="unexpected architecture"):
        validate_architecture(DEFAULT_CHECKPOINT, pinned_manifest(), *architecture)


@pytest.mark.parametrize(
    ("model_id", "explicit"),
    [
        (DEFAULT_CHECKPOINT.model_id, False),
        ("google/siglip2-base-patch16-224", True),
        ("google/siglip2-base-patch16-384", True),
        ("google/siglip2-so400m-patch16-384", True),
    ],
)
def test_acquire_default_and_explicit_checkpoint_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
    explicit: bool,
) -> None:
    checkpoint = checkpoint_for_id(model_id)
    manifest = pinned_manifest(model_id)
    files = object_value(manifest["files"])
    calls: list[str] = []

    def fake_download(
        url: str,
        target: Path,
        max_bytes: int,
        expected: str | None = None,
        seconds: float = 600,
        expected_length: int | None = None,
        validate: Callable[[bytes], None] | None = None,
    ) -> DownloadReceipt:
        meta = object_value(files[target.name])
        assert url == (
            f"https://huggingface.co/{model_id}/resolve/{checkpoint.revision}/"
            f"{target.name}?download=true"
        )
        assert max_bytes == expected_length == meta["byte_length"]
        assert expected == meta["sha256"]
        assert expected is not None
        assert seconds == 1800 and validate is None
        calls.append(target.name)
        target.write_bytes(b"synthetic artifact")
        return {"source": url, "sha256": expected, "byte_length": max_bytes}

    monkeypatch.setattr(acquire, "download", fake_download)
    model_dir = tmp_path / "model"
    argv = ["--model-dir", str(model_dir)]
    if explicit:
        argv.extend(("--model-id", model_id))
    acquire.main(argv)
    assert set(calls) == ARTIFACTS
    assert read_json(model_dir / "manifest.json") == manifest


@pytest.mark.parametrize("extra_kind", ["file", "symlink"])
def test_acquire_rejects_extra_preexisting_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_kind: str,
) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    extra = model_dir / "unexpected"
    if extra_kind == "file":
        extra.write_bytes(b"preexisting extra")
    else:
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside sentinel")
        extra.symlink_to(outside)

    def fake_download(
        url: str,
        target: Path,
        max_bytes: int,
        expected: str | None = None,
        seconds: float = 600,
        expected_length: int | None = None,
        validate: Callable[[bytes], None] | None = None,
    ) -> DownloadReceipt:
        target.write_bytes(b"synthetic artifact")
        assert expected is not None
        return {"source": url, "sha256": expected, "byte_length": max_bytes}

    monkeypatch.setattr(acquire, "download", fake_download)
    with pytest.raises(ValueError, match="unexpected model artifact"):
        acquire.main(["--model-dir", str(model_dir)])
    assert (
        extra.is_symlink()
        if extra_kind == "symlink"
        else extra.read_bytes() == b"preexisting extra"
    )


def test_acquire_rejects_unapproved_choice_before_directory_work(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        acquire.main(
            ["--model-dir", str(tmp_path / "model"), "--model-id", "local/arbitrary-model"]
        )
