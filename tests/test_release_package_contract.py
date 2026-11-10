"""Synthetic release contracts only: no uv build, installer, daemon or user setup."""

import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

LICENSE = b"Synthetic isolated license\n"
EXPRESSION = "LicenseRef-Netzwerkpunkt-Personal-Use-1.0"
COMMIT = "a" * 40
VERSION = "0.8.0rc17"


def script(name):
    source = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("contract_" + name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wheel(path, *, license_bytes=LICENSE):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "kirabridge-0.8.0rc17.dist-info/METADATA",
            (f"Name: kirabridge\nVersion: {VERSION}\nLicense-Expression: {EXPRESSION}\n"),
        )
        archive.writestr("kirabridge-0.8.0rc17.dist-info/licenses/LICENSE", license_bytes)


def package(tmp_path, target, *, legacy=False):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheel(artifacts / "kirabridge-0.8.0rc17-py3-none-any.whl")
    files = {
        "LICENSE": LICENSE,
        "payload/LICENSE": LICENSE,
        "payload/pyproject.toml": f'[project]\nlicense = "{EXPRESSION}"\n'.encode(),
        "install.sh": b"exit 99\n",
        "installer/install.py": b"raise SystemExit(99)\n",
    }
    pin = {
        "version": VERSION,
        "source_commit": COMMIT,
        "license": EXPRESSION,
        "license_sha256": hashlib.sha256(LICENSE).hexdigest(),
    }
    if target.startswith("Darwin"):
        name, root = "KiraBridge-macos.tar.gz", "KiraBridge"
        files["wheel/kirabridge-0.8.0rc17-py3-none-any.whl"] = next(
            artifacts.glob("*.whl")
        ).read_bytes()
        pin.update(
            commit=COMMIT,
            platforms=["Darwin-x86_64", "Darwin-arm64"],
            wheel="wheel/kirabridge-0.8.0rc17-py3-none-any.whl",
        )
    else:
        root = f"KiraBridge-{VERSION}-{target}"
        name = root + ".tar.gz"
        pin["platform"] = target
    if legacy:
        pin.pop("license")
        pin.pop("license_sha256")
    pin["files"] = {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
    files["release.json"] = json.dumps(pin).encode()
    with tarfile.open(artifacts / name, "w:gz") as archive:
        for key, data in files.items():
            info = tarfile.TarInfo(root + "/" + key)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    if not legacy:
        (artifacts / "LICENSE").write_bytes(LICENSE)
    return artifacts


class Prepared(Exception):
    pass


@pytest.mark.parametrize("target", ["Linux-x86_64", "Darwin-x86_64", "Darwin-arm64"])
def test_smoke_reaches_correct_isolated_preparation_for_actual_bundle_layout(
    tmp_path, monkeypatch, target
):
    module = script("release_smoke")
    artifacts = package(tmp_path, target)
    system, machine = target.split("-")
    monkeypatch.setattr(module.platform, "system", lambda: system)
    monkeypatch.setattr(module.platform, "machine", lambda: machine)

    def prepare(argv, **kwargs):
        if system == "Darwin":
            assert "prepare" in argv and "--service" in argv and "none" in argv
            assert "--prepare-only" not in argv and "--install-dir" not in argv
        else:
            assert "--prepare-only" in argv and "--install-dir" in argv
        raise Prepared

    monkeypatch.setattr(module, "run", prepare)
    with pytest.raises(Prepared):
        module.smoke(artifacts)


@pytest.mark.parametrize("host", ["linux", "darwin"])
def test_builder_emits_license_asset_and_matching_manifest_for_host(tmp_path, monkeypatch, host):
    module = script("build_release")
    # This fixture exercises source/license packaging; native Darwin packaging
    # has its own signed-app fixture and must never invoke Swift here.
    monkeypatch.setattr(module.sys, "platform", host)
    monkeypatch.setattr(module, "native_payload", lambda *a: ({}, {}, {}))
    library = {"threaddesk/pyproject.toml": b"[project]\n"}
    monkeypatch.setattr(module, "threaddesk_library", lambda *a: ("b" * 40, library))
    monkeypatch.chdir(tmp_path)
    inputs = {
        "LICENSE": LICENSE,
        "pyproject.toml": f'[project]\nversion = "{VERSION}"\nlicense = "{EXPRESSION}"\n'.encode(),
        "uv.lock": b"version = 1\n",
        "installer/install.py": b"# fixture\n",
        "installer/desktop.py": b"# isolated desktop transaction fixture\n",
        "installer/presentation.py": b"# isolated presentation fixture\n",
        "installer/visible_terminal.py": b"# isolated visibility fixture\n",
        "src/kirabridge/terminal_design.py": b"# isolated renderer fixture\n",
        "src/kirabridge/install_ui.py": b"# isolated UI fixture\n",
        "scripts/release-install.sh": b"# @PLATFORM@ @SOURCE@\n",
        "docs/INSTALL-MACOS.md": b"Fixture\n",
        f"docs/RELEASE-{VERSION}.md": b"Fixture\n",
    }
    for name, data in inputs.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def git(*args):
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return COMMIT
        if args[0] == "show":
            return "1"
        assert args == ("ls-files",)
        return "\n".join(inputs)

    def fake_uv(argv, **kwargs):
        assert argv[:3] == ["uv", "build", "--wheel"]
        wheel(Path(argv[-1]) / "kirabridge-0.8.0rc17-py3-none-any.whl")

    monkeypatch.setattr(module, "git", git)
    monkeypatch.setattr(module.subprocess, "run", fake_uv)
    monkeypatch.setattr(
        module.subprocess, "check_output", lambda argv: inputs[argv[-1].split(":", 1)[1]]
    )
    output = tmp_path / "output"
    module.build(output)
    if host == "darwin":
        assert [p.name for p in output.glob("*.tar.gz")] == ["KiraBridge-macos.tar.gz"]
    else:
        assert not (output / "KiraBridge-macos.tar.gz").exists()
    assert (output / "LICENSE").read_bytes() == LICENSE
    assert "  LICENSE\n" in (output / "SHA256SUMS").read_text()
    for path in output.glob("*.tar.gz"):
        with tarfile.open(path) as archive:
            pin = json.load(
                archive.extractfile(next(x for x in archive if x.name.endswith("/release.json")))
            )
        assert pin["license"] == EXPRESSION
        assert pin["license_sha256"] == hashlib.sha256(LICENSE).hexdigest()
        assert pin["source_commit"] == COMMIT
        if path.name == "KiraBridge-macos.tar.gz":
            assert pin["threaddesk"] == "b" * 40
            assert (
                pin["files"]["threaddesk/pyproject.toml"]
                == hashlib.sha256(b"[project]\n").hexdigest()
            )
        descriptor = pin["presentation"]
        assert descriptor["schema"] == "kirabridge.installer.presentation.v1"
        assert descriptor["palette"] == "#F06DB0"
        assert descriptor["output"] == "human-stderr-only"
        for name, expected in descriptor["assets"].items():
            with tarfile.open(path) as archive:
                member = next(item for item in archive if item.name.endswith("/" + name))
                data = archive.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest() == expected
        if path.name == "KiraBridge-macos.tar.gz":
            assert "installer/visible_terminal.py" in pin["files"]


def test_explicit_linux_server_target_skips_wheel_and_macos_bundle(tmp_path, monkeypatch):
    module = script("build_release")
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.chdir(tmp_path)
    inputs = {
        "LICENSE": LICENSE,
        "pyproject.toml": f'[project]\nversion = "{VERSION}"\nlicense = "{EXPRESSION}"\n'.encode(),
        "uv.lock": b"version = 1\n",
        "installer/install.py": b"# installer\n",
        "installer/presentation.py": b"# presentation\n",
        "src/kirabridge/terminal_design.py": b"# design\n",
        "src/kirabridge/install_ui.py": b"# ui\n",
        "scripts/release-install.sh": b"# @PLATFORM@ @SOURCE@\n",
        f"docs/RELEASE-{VERSION}.md": b"Fixture\n",
        "docs/INSTALL-LINUX-SERVER.de.md": b"de\n",
        "docs/INSTALL-LINUX-SERVER.md": b"en\n",
    }
    for name, data in inputs.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def git(*args):
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return COMMIT
        if args == ("ls-files",):
            return "\n".join(inputs)
        raise AssertionError(args)

    def fake_uv(*args, **kwargs):
        raise AssertionError("linux-server target must not build a wheel")

    monkeypatch.setattr(module, "git", git)
    monkeypatch.setattr(module.subprocess, "run", fake_uv)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda argv: inputs[argv[-1].split(":", 1)[1]],
    )
    output = tmp_path / "server-out"
    module.build(output, target="linux-server")
    archive = output / f"KiraBridge-{VERSION}-Linux-x86_64.tar.gz"
    assert archive.is_file()
    assert not (output / "KiraBridge-macos.tar.gz").exists()
    sidecar = (output / (archive.name + ".sha256")).read_text().split()[0]
    assert sidecar == hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive) as packed:
        pin = json.load(
            packed.extractfile(next(item for item in packed if item.name.endswith("/release.json")))
        )
        names = {item.name.split("/", 1)[1] for item in packed.getmembers()}
    assert pin["role"] == "linux-server"
    assert pin["gui_parity"] is False
    assert pin["service"] == "systemd-user"
    assert "installer/install.py" in names
    assert "INSTALL-DE.md" in names
    assert "INSTALL-EN.md" in names
    assert pin["files"]["installer/install.py"] == hashlib.sha256(b"# installer\n").hexdigest()


def rewrite_archive(artifacts, change):
    path = next(artifacts.glob("*.tar.gz"))
    with tarfile.open(path) as archive:
        files = {item.name: archive.extractfile(item).read() for item in archive}
    change(files)
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize(
    "target,old_name", [("Darwin-x86_64", False), ("Darwin-arm64", True), ("Linux-x86_64", False)]
)
def test_legacy_packages_require_pinned_license_copies_and_metadata(tmp_path, target, old_name):
    module = script("release_smoke")
    artifacts = package(tmp_path, target, legacy=True)
    if old_name:
        next(artifacts.glob("*.tar.gz")).rename(artifacts / f"KiraBridge-{VERSION}-{target}.tar.gz")
    if target.startswith("Linux"):

        def use_legacy_sums(files):
            key = next(name for name in files if name.endswith("/release.json"))
            pin = json.loads(files[key])
            entries = pin.pop("files")
            files[key] = json.dumps(pin).encode()
            root = key.rsplit("/", 1)[0]
            files[root + "/SHA256SUMS"] = "".join(
                digest + "  " + name + "\n" for name, digest in entries.items()
            ).encode()

        rewrite_archive(artifacts, use_legacy_sums)
    folder = tmp_path / "extracted"
    folder.mkdir()
    _, _, pin, separate = module.package_contract(artifacts, folder, target)
    assert pin["license"] == EXPRESSION and pin["source_commit"] == COMMIT
    assert not separate  # Old packages are never reported to have a separate asset.


@pytest.mark.parametrize("corruption", ["asset", "missing_asset", "wheel", "pin", "escape"])
def test_package_rejects_license_pin_and_archive_corruption_before_preparation(
    tmp_path, corruption
):
    module = script("release_smoke")
    artifacts = package(tmp_path, "Linux-x86_64")
    if corruption == "asset":
        (artifacts / "LICENSE").write_bytes(b"changed license")
    elif corruption == "missing_asset":
        (artifacts / "LICENSE").unlink()
    elif corruption == "wheel":
        wheel(next(artifacts.glob("*.whl")), license_bytes=b"changed license")
    else:

        def corrupt(files):
            if corruption == "escape":
                files["../must-not-exist"] = b"escape"
            else:
                key = next(name for name in files if name.endswith("/release.json"))
                pin = json.loads(files[key])
                pin["source_commit"] = "not-a-commit"
                files[key] = json.dumps(pin).encode()

        rewrite_archive(artifacts, corrupt)
    folder = tmp_path / "extracted"
    folder.mkdir()
    with pytest.raises((RuntimeError, AssertionError)):
        module.package_contract(artifacts, folder, "Linux-x86_64")
    assert not (tmp_path / "must-not-exist").exists()


def test_builder_bundles_threaddesk_library_at_the_ci_pin(tmp_path, monkeypatch):
    import subprocess

    module = script("build_release")
    repo = tmp_path / "threaddesk"
    (repo / "src/threaddesk").mkdir(parents=True)
    (repo / "src/threaddesk/__init__.py").write_text("")
    (repo / "pyproject.toml").write_text("[project]\n")
    (repo / "tests").mkdir()
    (repo / "tests/test_x.py").write_text("")
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
    for argv in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
    ):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, env=env)
    pin = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    monkeypatch.setattr(module, "git_blob", lambda c, n: f'LEGACY_TD = "{pin}"\n'.encode())
    assert module.threaddesk_library(COMMIT, repo) == (
        pin,
        {"threaddesk/pyproject.toml": b"[project]\n", "threaddesk/src/threaddesk/__init__.py": b""},
    )
    monkeypatch.setattr(module, "git_blob", lambda c, n: b'LEGACY_TD = "' + b"c" * 40 + b'"\n')
    with pytest.raises((SystemExit, subprocess.CalledProcessError)):
        module.threaddesk_library(COMMIT, repo)
