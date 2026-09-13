"""Build and inspect autonomous offline wheel and source distributions."""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import venv
import zipfile
from pathlib import Path

from memotrace_ml.identity import implementation_files

LICENSE_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"
MANIFESTS = {
    "model-manifest.json",
    "model-manifest-siglip2-base-patch16-384.json",
    "model-manifest-siglip2-so400m-patch16-384.json",
}


def test_offline_distributions_have_exact_resources_license_and_install(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    license_bytes = (root / "LICENSE").read_bytes()
    assert hashlib.sha256(license_bytes).hexdigest() == LICENSE_SHA256
    output = tmp_path / "distributions"
    output.mkdir()
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "LANG": "C.UTF-8",
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
    }
    Path(environment["HOME"]).mkdir(mode=0o700)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "hatchling",
            "build",
            "-t",
            "sdist",
            "-t",
            "wheel",
            "-d",
            str(output),
        ],
        cwd=root,
        env=environment,
        check=True,
        timeout=120,
    )
    wheels = list(output.glob("*.whl"))
    sdists = list(output.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    expected_sources = {"memotrace_ml/" + name for name in implementation_files()}
    expected_package = expected_sources | {"memotrace_ml/" + name for name in MANIFESTS}
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        assert {name for name in names if name.startswith("memotrace_ml/")} == expected_package
        wheel_licenses = [name for name in names if name.endswith(".dist-info/licenses/LICENSE")]
        assert len(wheel_licenses) == 1
        assert wheel.read(wheel_licenses[0]) == license_bytes
        for manifest in MANIFESTS:
            assert wheel.read("memotrace_ml/" + manifest) == (root / manifest).read_bytes()
    with tarfile.open(sdists[0], "r:gz") as sdist:
        sdist_names = sdist.getnames()
        prefixes = {name.split("/", 1)[0] for name in sdist_names}
        assert len(prefixes) == 1
        prefix = prefixes.pop()
        package = {
            name.removeprefix(prefix + "/")
            for name in sdist_names
            if name.startswith(prefix + "/memotrace_ml/") and sdist.getmember(name).isfile()
        }
        assert package == expected_sources
        member = sdist.extractfile(prefix + "/LICENSE")
        assert member is not None and member.read() == license_bytes
        for manifest in MANIFESTS:
            member = sdist.extractfile(prefix + "/" + manifest)
            assert member is not None and member.read() == (root / manifest).read_bytes()
        assert prefix + "/pyproject.toml" in sdist_names
        assert prefix + "/uv.lock" in sdist_names
    uv = shutil.which("uv")
    assert uv is not None
    install = tmp_path / "install"
    venv.EnvBuilder(with_pip=False).create(install)
    python = install / "bin" / "python"
    subprocess.run(
        [uv, "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheels[0])],
        env=environment,
        check=True,
        timeout=120,
    )
    subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            (
                "from importlib.resources import files; import memotrace_ml; "
                "assert files('memotrace_ml').joinpath('model-manifest.json').is_file()"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        timeout=30,
    )
