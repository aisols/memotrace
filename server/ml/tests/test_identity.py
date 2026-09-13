"""Implementation content identity survives wheel paths and invalidates generations."""

import base64
import copy
import hashlib
import importlib.metadata
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest

from memotrace_ml.common import JSON, fingerprint
from memotrace_ml.identity import (
    distribution_record_identity,
    fingerprint_with_implementation,
    implementation_digest,
    implementation_files,
    numerical_runtime_identity,
)


def test_source_and_wheel_resources_have_identical_implementation_digest(tmp_path: Path) -> None:
    source = files("memotrace_ml")
    archive = tmp_path / "synthetic-wheel.zip"
    with zipfile.ZipFile(archive, "w") as wheel:
        for name in implementation_files():
            wheel.writestr("memotrace_ml/" + name, source.joinpath(name).read_bytes())
    with zipfile.ZipFile(archive) as wheel:
        assert (
            implementation_digest(zipfile.Path(wheel, "memotrace_ml/")) == implementation_digest()
        )


def test_changed_or_new_encoding_code_changes_model_and_generation(tmp_path: Path) -> None:
    code = tmp_path / "images.py"
    code.write_bytes(b"# synthetic encoding version 1\n")
    settings: dict[str, JSON] = {"model": "test-only"}
    _, first = fingerprint_with_implementation(settings, tmp_path)
    code.write_bytes(b"# synthetic encoding version 2\n")
    _, second = fingerprint_with_implementation(settings, tmp_path)
    assert first != second
    assert (
        hashlib.sha256((first + ":policy").encode()).hexdigest()
        != hashlib.sha256((second + ":policy").encode()).hexdigest()
    )
    (tmp_path / "new_encoding_helper.py").write_bytes(b"# additional first-party implementation\n")
    _, third = fingerprint_with_implementation(settings, tmp_path)
    assert third != second


def test_installed_record_and_numerical_runtime_are_path_free_identity_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    numpy = distribution_record_identity("numpy")
    assert numpy["version"] == "2.2.6"
    assert isinstance(numpy["content_sha256"], str) and len(numpy["content_sha256"]) == 64
    runtime = numerical_runtime_identity(
        ("numpy",),
        {
            "version": "test-torch",
            "git_version": "test-git",
            "debug": False,
            "cpu_capability": "test-capability",
        },
    )
    encoded = str(runtime)
    assert "/home/" not in encoded and "/tmp/" not in encoded
    baseline = fingerprint(runtime)
    for section, key, replacement in (
        ("python", "version", "different-python"),
        ("libc", "version", "different-libc"),
        ("torch_build", "cpu_capability", "different-capability"),
    ):
        changed = copy.deepcopy(runtime)
        nested = changed[section]
        assert isinstance(nested, dict)
        nested[key] = replacement
        assert fingerprint(changed) != baseline
    changed = copy.deepcopy(runtime)
    features = changed["cpu_features"]
    assert isinstance(features, list)
    features.append("synthetic-feature-change")
    assert fingerprint(changed) != baseline

    selected = [synthetic_distribution(tmp_path / "first")]

    def distribution(_name: str) -> importlib.metadata.Distribution:
        return selected[0]

    monkeypatch.setattr(importlib.metadata, "distribution", distribution)
    baseline_distribution = distribution_record_identity("numerical")
    selected[0] = synthetic_distribution(tmp_path / "second")
    relocated = distribution_record_identity("numerical")
    assert relocated == baseline_distribution
    encoded = str(relocated)
    assert str(tmp_path / "first") not in encoded
    assert str(tmp_path / "second") not in encoded

    for changed_distribution in (
        synthetic_distribution(tmp_path / "package-change", package=b"changed package"),
        synthetic_distribution(tmp_path / "native-change", native=b"changed native library"),
    ):
        selected[0] = changed_distribution
        assert distribution_record_identity("numerical") != baseline_distribution


def test_distribution_identity_fails_closed_on_record_and_filesystem_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "distribution"
    selected = synthetic_distribution(root)
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: selected)
    package = root / "lib/python3.12/site-packages/numerical/__init__.py"
    package.write_bytes(b"x" * len(package.read_bytes()))
    with pytest.raises(ValueError, match="RECORD digest"):
        distribution_record_identity("numerical")

    size_root = tmp_path / "size"
    selected = synthetic_distribution(size_root)
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: selected)
    record = size_root / "lib/python3.12/site-packages/numerical-1.0.dist-info/RECORD"
    lines = record.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("numerical/__init__.py,"))
    prefix, declared_size = lines[index].rsplit(",", 1)
    lines[index] = f"{prefix},{int(declared_size) + 1}"
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="RECORD metadata"):
        distribution_record_identity("numerical")

    selected = synthetic_distribution(tmp_path / "missing")
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: selected)
    Path(str(selected.locate_file("numerical/__init__.py"))).unlink()
    with pytest.raises(ValueError, match="missing or unsafe"):
        distribution_record_identity("numerical")


@pytest.mark.parametrize(
    "unsafe",
    ["symlink", "nonregular", "escape", "unhashed", "malformed-hash", "malformed-size"],
)
def test_distribution_identity_rejects_unsafe_or_malformed_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    extra_record: tuple[str, bytes, bool | str] | None = None
    if unsafe == "escape":
        extra_record = ("../outside.py", b"outside", True)
    elif unsafe == "unhashed":
        extra_record = ("numerical/unhashed.py", b"unhashed", False)
    elif unsafe == "malformed-hash":
        extra_record = ("numerical/malformed.py", b"malformed", "malformed")
    elif unsafe == "malformed-size":
        extra_record = ("numerical/malformed.py", b"malformed", "malformed-size")
    root = tmp_path / unsafe
    selected = synthetic_distribution(root, extra_record=extra_record)
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: selected)
    if unsafe == "symlink":
        package = Path(str(selected.locate_file("numerical/__init__.py")))
        outside = tmp_path / "outside.py"
        outside.write_bytes(package.read_bytes())
        package.unlink()
        package.symlink_to(outside)
    elif unsafe == "nonregular":
        package = Path(str(selected.locate_file("numerical/__init__.py")))
        package.unlink()
        package.mkdir()
    with pytest.raises(ValueError):
        distribution_record_identity("numerical")


def synthetic_distribution(
    root: Path,
    *,
    package: bytes = b"# synthetic numerical package\n",
    native: bytes = b"synthetic native library\n",
    extra_record: tuple[str, bytes, bool | str] | None = None,
) -> importlib.metadata.Distribution:
    site_packages = root / "lib/python3.12/site-packages"
    metadata = site_packages / "numerical-1.0.dist-info"
    metadata.mkdir(parents=True)
    package_directory = site_packages / "numerical"
    package_directory.mkdir()
    (package_directory / "__init__.py").write_bytes(package)
    native_directory = site_packages / "numerical.libs"
    native_directory.mkdir()
    (native_directory / "libnumerical.so").write_bytes(native)
    scripts = root / "bin"
    scripts.mkdir()
    (scripts / "f2py").write_text(f"#!{root}/bin/python\n", encoding="utf-8")
    metadata_bytes = b"Metadata-Version: 2.4\nName: numerical\nVersion: 1.0\n"
    (metadata / "METADATA").write_bytes(metadata_bytes)
    declared: list[tuple[str, bytes]] = [
        ("../../../bin/f2py", (scripts / "f2py").read_bytes()),
        ("numerical/__init__.py", package),
        ("numerical.libs/libnumerical.so", native),
        ("numerical-1.0.dist-info/METADATA", metadata_bytes),
    ]
    if extra_record is not None:
        name, raw, hashed = extra_record
        target = site_packages / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if hashed == "malformed":
            extra_line = f"{name},sha256=not-base64,{len(raw)}"
        elif hashed == "malformed-size":
            digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
            extra_line = f"{name},sha256={digest},not-a-size"
        elif hashed:
            declared.append((name, raw))
            extra_line = ""
        else:
            extra_line = f"{name},,{len(raw)}"
    else:
        extra_line = ""

    def record_line(name: str, raw: bytes) -> str:
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        return f"{name},sha256={digest},{len(raw)}"

    lines = [record_line(name, raw) for name, raw in declared]
    if extra_line:
        lines.append(extra_line)
    lines.append("numerical-1.0.dist-info/RECORD,,")
    (metadata / "RECORD").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return importlib.metadata.Distribution.at(metadata)
