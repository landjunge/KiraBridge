"""A shared version string must not make an old daemon pass upgrade readiness."""

import contextlib
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class InstallerSourceReadinessTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "installer_source_test", Path(__file__).parents[1] / "installer/install.py"
        )
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.config = self.root / "config.toml"
        self.config.write_text('data_dir = "/unused-fixture"\n')
        self.release = self.root / "new"
        self.expected = {
            "source_package_path": str(
                self.release / "source/.venv/lib/python3.11/site-packages/kirabridge"
            ),
            "source_tree_sha256": "b" * 64,
            "source_file_count": 2,
        }
        self.health = {
            "version": "0.8.0rc40",
            "dispatcher_active": True,
            "runtime": {**self.expected, "config_sha256": self.installer.sha(self.config)},
        }

    def wait(self, values):
        ticks = iter(range(100))
        with (
            patch.object(self.installer, "release_source", return_value=self.expected, create=True),
            patch.object(self.installer, "cli", side_effect=values) as query,
            patch.object(self.installer.time, "sleep"),
            patch.object(self.installer.time, "monotonic", side_effect=lambda: next(ticks)),
        ):
            result = self.installer.wait_health(
                SimpleNamespace(config=self.config), self.release, "0.8.0rc40"
            )
            return result, query.call_count

    def test_same_version_old_daemon_must_settle_to_requested_source(self):
        old = {
            **self.health,
            "runtime": {**self.health["runtime"], "source_package_path": "/old/kirabridge"},
        }
        result, calls = self.wait([old, self.health])
        self.assertEqual(calls, 2)
        self.assertEqual(result["runtime"], self.health["runtime"])

    def test_mismatched_source_hash_and_file_count_are_not_ready(self):
        for field, value in (("source_tree_sha256", "a" * 64), ("source_file_count", 1)):
            with self.subTest(field=field):
                stale = {**self.health, "runtime": {**self.health["runtime"], field: value}}
                _, calls = self.wait([stale, self.health])
                self.assertEqual(calls, 2)

    def test_old_source_never_counts_as_success_after_deadline(self):
        stale = {
            **self.health,
            "runtime": {**self.health["runtime"], "source_tree_sha256": "a" * 64},
        }
        with self.assertRaisesRegex(RuntimeError, "readiness not proven"):
            self.wait([stale] * 30)

    def test_release_source_uses_isolated_venv_and_matches_runtime_manifest(self):
        package = Path(self.expected["source_package_path"])
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('version = "fixture"\n')
        (package / "module.py").write_text("value = 1\n")
        (package / "ignored.txt").write_text("not Python source")
        with patch.object(
            self.installer, "run", return_value=json.dumps(str(package)).encode()
        ) as run:
            actual = self.installer.release_source(self.release)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], [self.installer.python(self.release), "-I", "-c"])
        manifest = {p.name: self.installer.sha(p) for p in package.glob("*.py")}
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(actual, {**self.expected, "source_tree_sha256": digest})

    def test_release_source_refuses_package_from_another_environment(self):
        package = self.root / "foreign/kirabridge"
        package.mkdir(parents=True)
        (self.release / "source/.venv").mkdir(parents=True)
        with patch.object(self.installer, "run", return_value=json.dumps(str(package)).encode()):
            with self.assertRaisesRegex(RuntimeError, "outside its release"):
                self.installer.release_source(self.release)

    def rollback(self, previous):
        prefix = self.root / "install"
        prefix.mkdir()
        backup = self.root / "backup"
        backup.mkdir()
        args = SimpleNamespace(
            prefix=prefix,
            config=self.config,
            launcher=self.root / "launcher",
            plist=self.root / "service.plist",
            service="launchd",
        )
        active = {
            "release": str(self.release),
            "backup": str(backup),
            "previous": previous,
            "was_loaded": True,
            "previous_version": "0.8.0rc40",
            "previous_source": self.expected,
            "had_wrapper": False,
            "had_plist": False,
            **{key: str(getattr(args, key)) for key in ("config", "launcher", "plist", "service")},
        }
        (prefix / "current.json").write_text(json.dumps(active))
        with (
            patch.object(self.installer, "require_visible_terminal"),
            patch.object(self.installer, "idle_guard", return_value=contextlib.nullcontext()),
            patch.object(self.installer, "require_queue_compatibility"),
            patch.object(self.installer, "stop_service"),
            patch.object(self.installer, "start_service"),
            patch.object(self.installer, "wait_health") as wait,
        ):
            self.installer.rollback(args)
        return wait.call_args

    def test_rollback_verifies_previous_release_instead_of_failed_candidate(self):
        old = self.root / "previous"
        call = self.rollback({"release": str(old)})
        self.assertEqual(call.args[1:], (old, "0.8.0rc40"))

    def test_manual_previous_install_uses_recorded_source_identity(self):
        call = self.rollback(None)
        self.assertEqual(call.args[1:], (self.release, "0.8.0rc40"))
        self.assertEqual(call.kwargs["expected_source"], self.expected)


if __name__ == "__main__":
    unittest.main()
