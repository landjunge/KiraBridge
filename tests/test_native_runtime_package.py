"""Synthetic native package fixtures; never compile, sign, execute or install a real app."""

import hashlib
import importlib.util
import json
import os
import plistlib
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

COMMIT = "a" * 40
VERSION = "0.8.0rc21"
APP = "native/KiraBridge.app"
BINARY = APP + "/Contents/MacOS/KiraBridge"
INFO = APP + "/Contents/Info.plist"
RESOURCES = APP + "/Contents/_CodeSignature/CodeResources"


def script(name, directory="scripts"):
    path = Path(__file__).resolve().parents[1] / directory / (name + ".py")
    spec = importlib.util.spec_from_file_location("native_package_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def app_files():
    return {
        BINARY: (
            b"\xcf\xfa\xed\xfe"
            + (0x01000007).to_bytes(4, "little")
            + bytes(4)
            + (2).to_bytes(4, "little")
            + bytes(16)
            + b"synthetic non-executable native-code fixture\x00\xff"
        ),
        INFO: plistlib.dumps(
            {
                "CFBundleIdentifier": "de.netzwerkpunkt.kirabridge",
                "CFBundleExecutable": "KiraBridge",
                "KiraBridgeSystemProtocol": 1,
                "KiraBridgeSourceCommit": COMMIT,
                "KiraBridgeVersion": VERSION,
            }
        ),
        RESOURCES: b"synthetic signature fixture; not a real signed app",
    }


def put(root, name, data, mode=0o644):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def descriptor():
    return {
        "schema": "kirabridge.native-app.v1",
        "path": APP,
        "protocol": 1,
        "source_commit": COMMIT,
        "binary_sha256": hashlib.sha256(app_files()[BINARY]).hexdigest(),
        "signing": "ad-hoc",
        "architecture": "x86_64",
    }


def make_bundle(tmp_path, *, native=True):
    bundle = tmp_path / "bundle"
    files = {"payload/uv.lock": b"locked fixture", "wheel/test.whl": b"fixture wheel"}
    modes = {}
    if native:
        files.update(app_files())
        modes = {name: 0o755 if name == BINARY else 0o644 for name in app_files()}
    for name, data in files.items():
        put(bundle, name, data, modes.get(name, 0o644))
    pin = {
        "version": VERSION,
        "commit": COMMIT,
        "source_commit": COMMIT,
        "wheel": "wheel/test.whl",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    if native:
        pin.update(native_app_required=True, native_app=descriptor(), file_modes=modes)
    save(bundle, pin)
    return bundle, pin


def save(bundle, pin):
    (bundle / "release.json").write_text(json.dumps(pin))


def mocked_installer(monkeypatch):
    module, calls = script("install", "installer"), []
    monkeypatch.setattr(module.shutil, "which", lambda name: "/test/uv")
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(module, "cli_version", lambda destination: VERSION)

    def run(argv, **kwargs):
        calls.append(tuple(map(str, argv)))
        if argv == ["/test/uv", "--version"]:
            return b"uv 0.11.6 fixture\n"
        assert argv[0] == "/test/uv"  # Native app, launchctl and UI are never invoked.

    monkeypatch.setattr(module, "run", run)
    return module, calls


def test_fresh_prepare_embeds_exact_native_bytes_modes_and_release_pin(tmp_path, monkeypatch):
    module, calls = mocked_installer(monkeypatch)
    bundle, pin = make_bundle(tmp_path)
    args = SimpleNamespace(
        bundle=bundle, prefix=tmp_path / "isolated", cache_dir=tmp_path / "cache"
    )
    destination = module.prepare_bundle(args)
    saved = json.loads((destination / "release.json").read_text())
    assert saved["source_commit"] == COMMIT and saved["native_app"] == descriptor()
    assert saved["native_app_required"] is True
    assert set(saved["files"]) == set(app_files())
    for name, data in app_files().items():
        assert (destination / name).read_bytes() == data
        assert (destination / name).stat().st_mode & 0o777 == pin["file_modes"][name]
    assert len(calls) == 3  # uv version/sync/pip only; no service or native invocation.
    assert module.prepare_bundle(args) == destination
    assert len(calls) == 3  # Idempotent verification does not reinstall or replay.


def test_private_bootstrap_umask_preserves_pinned_native_modes(tmp_path, monkeypatch):
    module, _ = mocked_installer(monkeypatch)
    bundle, pin = make_bundle(tmp_path)
    previous_umask = os.umask(0o077)
    try:
        result = module.prepare_bundle(
            SimpleNamespace(
                bundle=bundle, prefix=tmp_path / "isolated", cache_dir=tmp_path / "cache"
            )
        )
    finally:
        os.umask(previous_umask)
    for name, mode in pin["file_modes"].items():
        assert (result / name).stat().st_mode & 0o777 == mode
    assert (result / "release.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="Supported Mac/Linux bootstrap uses POSIX tar")
def test_hash_checked_archive_extracts_and_prepares_exact_modes_under_private_umask(
    tmp_path, monkeypatch
):
    module, calls = mocked_installer(monkeypatch)
    bundle, pin = make_bundle(tmp_path)
    package = tmp_path / "synthetic-native.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.add(path, arcname="KiraBridge/" + path.relative_to(bundle).as_posix())
    expected_archive_digest = hashlib.sha256(package.read_bytes()).hexdigest()
    extracted = tmp_path / "private-scratch"
    extracted.mkdir(mode=0o700)
    # Bootstrap verifies its pinned archive hash before permitting exact modes.
    assert hashlib.sha256(package.read_bytes()).hexdigest() == expected_archive_digest
    subprocess.run(
        ["/usr/bin/tar", "-xpzf", str(package), "-C", str(extracted)],
        check=True,
        capture_output=True,
        timeout=5,
        umask=0o077,
    )
    unpacked = extracted / "KiraBridge"
    for name, mode in pin["file_modes"].items():
        assert (unpacked / name).stat().st_mode & 0o777 == mode
    previous_umask = os.umask(0o077)
    try:
        result = module.prepare_bundle(
            SimpleNamespace(
                bundle=unpacked, prefix=tmp_path / "isolated", cache_dir=tmp_path / "cache"
            )
        )
    finally:
        os.umask(previous_umask)
    for name, data in app_files().items():
        assert (result / name).read_bytes() == data
        assert (result / name).stat().st_mode & 0o777 == pin["file_modes"][name]
    assert len(calls) == 3  # Only mocked uv version/sync/pip; no native app or service.


def test_isolated_upgrade_preserves_previous_release_and_current_link(tmp_path, monkeypatch):
    module, _ = mocked_installer(monkeypatch)
    bundle, _ = make_bundle(tmp_path)
    prefix = tmp_path / "isolated"
    previous = prefix / "releases/previous-verified-release"
    previous.mkdir(parents=True)
    previous.parent.chmod(0o700)
    (previous / "recovery-marker").write_bytes(b"preserve previous runtime")
    current = prefix / "current"
    current.symlink_to(previous)
    destination = module.prepare_bundle(
        SimpleNamespace(bundle=bundle, prefix=prefix, cache_dir=tmp_path / "cache")
    )
    assert destination != previous and current.resolve() == previous
    assert (previous / "recovery-marker").read_bytes() == b"preserve previous runtime"


@pytest.mark.parametrize(
    "corruption",
    [
        "descriptor_missing",
        "required_missing",
        "commit",
        "binary_pin",
        "mode",
        "unlisted",
        "missing_signature",
        "symlink",
        "ancestor_symlink",
        "checksum",
    ],
)
def test_native_corruption_refuses_before_runtime_preparation(tmp_path, monkeypatch, corruption):
    module, calls = mocked_installer(monkeypatch)
    bundle, pin = make_bundle(tmp_path)
    if corruption == "descriptor_missing":
        del pin["native_app"]
    elif corruption == "required_missing":
        del pin["native_app_required"]
    elif corruption == "commit":
        pin["native_app"]["source_commit"] = "b" * 40
    elif corruption == "binary_pin":
        pin["native_app"]["binary_sha256"] = "b" * 64
    elif corruption == "mode":
        (bundle / BINARY).chmod(0o644)
    elif corruption == "unlisted":
        put(bundle, APP + "/Contents/unknown", b"unlisted")
    elif corruption == "missing_signature":
        (bundle / RESOURCES).unlink()
        del pin["files"][RESOURCES]
        del pin["file_modes"][RESOURCES]
    elif corruption == "symlink":
        (bundle / BINARY).unlink()
        (bundle / BINARY).symlink_to(tmp_path / "foreign")
    elif corruption == "ancestor_symlink":
        (bundle / APP).rename(tmp_path / "foreign-app")
        (bundle / APP).symlink_to(tmp_path / "foreign-app", target_is_directory=True)
    else:
        (bundle / BINARY).write_bytes(b"changed code")
    save(bundle, pin)
    prefix = tmp_path / "isolated"
    with pytest.raises(RuntimeError):
        module.prepare_bundle(SimpleNamespace(bundle=bundle, prefix=prefix))
    assert calls == [] and not prefix.exists()


def test_existing_release_native_tampering_is_preserved_and_refused(tmp_path, monkeypatch):
    module, calls = mocked_installer(monkeypatch)
    bundle, _ = make_bundle(tmp_path)
    args = SimpleNamespace(
        bundle=bundle, prefix=tmp_path / "isolated", cache_dir=tmp_path / "cache"
    )
    destination = module.prepare_bundle(args)
    (destination / BINARY).write_bytes(b"changed installed code")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        module.prepare_bundle(args)
    assert (destination / BINARY).read_bytes() == b"changed installed code" and len(calls) == 3


def test_wrong_native_architecture_is_rejected_before_runtime_creation(tmp_path, monkeypatch):
    module, calls = mocked_installer(monkeypatch)
    monkeypatch.setattr(module.sys, "platform", "darwin")
    bundle, pin = make_bundle(tmp_path)
    pin["native_app"]["architecture"] = "arm64"
    save(bundle, pin)
    prefix = tmp_path / "isolated"
    with pytest.raises(RuntimeError, match="architecture"):
        module.prepare_bundle(SimpleNamespace(bundle=bundle, prefix=prefix))
    assert calls == [] and not prefix.exists()


def test_actual_macho_cpu_must_match_even_when_manifest_hashes_are_updated(tmp_path, monkeypatch):
    module, calls = mocked_installer(monkeypatch)
    bundle, pin = make_bundle(tmp_path)
    binary = bytearray((bundle / BINARY).read_bytes())
    binary[4:8] = (0x0100000C).to_bytes(4, "little")  # ARM code declared as Intel.
    (bundle / BINARY).write_bytes(binary)
    digest = hashlib.sha256(binary).hexdigest()
    pin["files"][BINARY] = digest
    pin["native_app"]["binary_sha256"] = digest
    save(bundle, pin)
    prefix = tmp_path / "isolated"
    with pytest.raises(RuntimeError, match="Mach-O architecture"):
        module.prepare_bundle(SimpleNamespace(bundle=bundle, prefix=prefix))
    assert calls == [] and not prefix.exists()


def test_existing_release_symlink_is_not_executed_or_replaced(tmp_path, monkeypatch):
    module, calls = mocked_installer(monkeypatch)
    bundle, _ = make_bundle(tmp_path)
    prefix = tmp_path / "isolated"
    releases = prefix / "releases"
    releases.mkdir(parents=True, mode=0o700)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    link = releases / (VERSION + "-" + COMMIT[:12])
    link.symlink_to(foreign)
    with pytest.raises(RuntimeError, match="symlink refused"):
        module.prepare_bundle(SimpleNamespace(bundle=bundle, prefix=prefix))
    assert link.is_symlink() and list(foreign.iterdir()) == [] and calls == []


def test_copy_detects_source_change_after_preflight_and_removes_only_new_release(
    tmp_path, monkeypatch
):
    module, _ = mocked_installer(monkeypatch)
    bundle, _ = make_bundle(tmp_path)
    original = module.copy_native

    def changed(root, destination, contract):
        (root / BINARY).write_bytes(b"changed between verify and copy")
        return original(root, destination, contract)

    monkeypatch.setattr(module, "copy_native", changed)
    prefix = tmp_path / "isolated"
    with pytest.raises(RuntimeError, match="changed during verified copy"):
        module.prepare_bundle(
            SimpleNamespace(bundle=bundle, prefix=prefix, cache_dir=tmp_path / "cache")
        )
    assert list((prefix / "releases").iterdir()) == []


def test_legacy_bundle_remains_supported_without_native_requirement(tmp_path, monkeypatch):
    module, _ = mocked_installer(monkeypatch)
    bundle, _ = make_bundle(tmp_path, native=False)
    result = module.prepare_bundle(
        SimpleNamespace(bundle=bundle, prefix=tmp_path / "isolated", cache_dir=tmp_path / "cache")
    )
    assert not (result / "native").exists()
    assert "native_app" not in json.loads((result / "release.json").read_text())


def test_new_native_source_cannot_downgrade_itself_to_legacy_bundle(tmp_path, monkeypatch):
    module, calls = mocked_installer(monkeypatch)
    bundle, pin = make_bundle(tmp_path, native=False)
    member = "payload/src/kirabridge/platform_adapters/macos/system_transport.py"
    put(bundle, member, b"new native transport source")
    pin["files"][member] = hashlib.sha256((bundle / member).read_bytes()).hexdigest()
    save(bundle, pin)
    with pytest.raises(RuntimeError, match="descriptor is missing"):
        module.prepare_bundle(SimpleNamespace(bundle=bundle, prefix=tmp_path / "isolated"))
    assert calls == []


def test_wheel_must_be_a_safe_checksum_pinned_bundle_member(tmp_path, monkeypatch):
    module, calls = mocked_installer(monkeypatch)
    bundle, pin = make_bundle(tmp_path)
    pin["wheel"] = "../foreign.whl"
    save(bundle, pin)
    with pytest.raises(RuntimeError, match="checksum-pinned member"):
        module.prepare_bundle(SimpleNamespace(bundle=bundle, prefix=tmp_path / "isolated"))
    assert calls == []


def test_new_native_revision_source_install_requires_its_built_runtime_bundle(
    tmp_path, monkeypatch
):
    module = script("install", "installer")
    monkeypatch.setattr(module.sys, "platform", "darwin")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "rev-parse" in argv:
            return COMMIT.encode()
        if "show" in argv:
            return f'[project]\nversion="{VERSION}"\n'.encode()
        assert "ls-tree" in argv
        return b"src/kirabridge/platform_adapters/macos/system_transport.py\n"

    monkeypatch.setattr(module, "run", run)
    prefix = tmp_path / "isolated"
    with pytest.raises(RuntimeError, match="release --bundle package"):
        module.prepare(SimpleNamespace(bundle=None, ref=COMMIT, repo=tmp_path, prefix=prefix))
    assert len(calls) == 3 and not prefix.exists()


def builder_fixture(tmp_path, monkeypatch, host):
    module = script("build_release")
    monkeypatch.setattr(module.sys, "platform", host)
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.chdir(tmp_path)
    inputs = {
        "LICENSE": b"fixture license",
        "pyproject.toml": f'[project]\nversion="{VERSION}"\nlicense="private"\n'.encode(),
        "uv.lock": b"fixture lock",
        "installer/install.py": b"fixture installer",
        "installer/presentation.py": b"fixture presentation",
        "installer/visible_terminal.py": b"fixture guard",
        "src/kirabridge/terminal_design.py": b"fixture design",
        "src/kirabridge/install_ui.py": b"fixture ui",
        "scripts/release-install.sh": b"@PLATFORM@ @SOURCE@",
        "docs/INSTALL-MACOS.md": b"fixture install",
        f"docs/RELEASE-{VERSION}.md": b"fixture release",
    }
    for name, data in inputs.items():
        put(tmp_path, name, data)

    def git(*args):
        return {
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): COMMIT,
            ("show", "-s", "--format=%ct", COMMIT): "1",
            ("ls-files",): "\n".join(inputs),
        }[args]

    def run(argv, **kwargs):
        if argv[:3] == ["uv", "build", "--wheel"]:
            (Path(argv[-1]) / "fixture.whl").write_bytes(b"fixture wheel")
        else:
            assert host == "darwin" and argv[:3] == ["/usr/bin/codesign", "--verify", "--strict"]

    builds = []

    def native_build(destination):
        assert host == "darwin"
        builds.append(destination)
        for name, data in app_files().items():
            relative = name.removeprefix(APP + "/")
            put(destination, relative, data, 0o755 if name == BINARY else 0o644)
        return destination

    monkeypatch.setattr(module, "git", git)

    def check_output(argv, **kwargs):
        if argv[:2] == ["/usr/bin/lipo", "-archs"]:
            return b"x86_64\n"
        return inputs[argv[-1].split(":", 1)[1]]

    monkeypatch.setattr(module.subprocess, "check_output", check_output)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "build_native_app", native_build)
    return module, builds


def test_darwin_runtime_contains_exact_signed_app_members_and_modes(tmp_path, monkeypatch):
    module, builds = builder_fixture(tmp_path, monkeypatch, "darwin")
    output = tmp_path / "out"
    module.build(output)
    assert len(builds) == 1 and not builds[0].exists()  # Private compiler staging removed.
    with tarfile.open(output / "KiraBridge-macos.tar.gz") as archive:
        pin = json.load(archive.extractfile("KiraBridge/release.json"))
        assert pin["native_app_required"] is True and pin["native_app"] == descriptor()
        for name, data in app_files().items():
            member = archive.getmember("KiraBridge/" + name)
            assert archive.extractfile(member).read() == data
            assert member.mode == pin["file_modes"][name]
            assert pin["files"][name] == hashlib.sha256(data).hexdigest()
    assert (output / "install-macos.sh").is_file()
    bootstrap = (output / "install-macos.sh").read_text()
    assert bootstrap.index("shasum -a 256 -c expected.sha256") < bootstrap.index("tar -xpzf ")


def test_linux_build_never_invokes_native_builder_or_emits_mac_artifacts(tmp_path, monkeypatch):
    module, builds = builder_fixture(tmp_path, monkeypatch, "linux")
    output = tmp_path / "out"
    module.build(output)
    assert builds == []
    assert not (output / "KiraBridge-macos.tar.gz").exists()
    assert not (output / "install-macos.sh").exists()
    assert (output / "fixture.whl.sha256").is_file()
    assert list(output.glob("KiraBridge-*-Linux-x86_64.tar.gz"))
    with tarfile.open(next(output.glob("KiraBridge-*-Linux-x86_64.tar.gz"))) as archive:
        assert not any("/native/" in item.name for item in archive)


def test_builder_refuses_signed_companion_for_wrong_actual_cpu(tmp_path, monkeypatch):
    module, _ = builder_fixture(tmp_path, monkeypatch, "darwin")
    original = module.subprocess.check_output

    def wrong_cpu(argv, **kwargs):
        if argv[:2] == ["/usr/bin/lipo", "-archs"]:
            return b"arm64\n"
        return original(argv, **kwargs)

    monkeypatch.setattr(module.subprocess, "check_output", wrong_cpu)
    output = tmp_path / "out"
    with pytest.raises(RuntimeError, match="CPU architecture"):
        module.build(output)
    assert not (output / "KiraBridge-macos.tar.gz").exists()
