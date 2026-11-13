"""Adversarial source guards only; no builds, providers or installed data."""

import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "personal_use_checker", ROOT / "scripts/check_personal_use_license.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class LicenseRegressionTests(unittest.TestCase):
    def test_exact_license_reference_and_license_file_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "LICENSE").write_bytes(b"existing product license\n")
            package = root / "packages/crypto"
            package.mkdir(parents=True)
            manifest = package / "package.json"
            for value, accepted in [
                (CHECK.ALLOWED_LICENSE_REF, True),
                ("LicenseRef-Netzwerkpunkt-Commercial-2.0", False),
                (CHECK.ALLOWED_LICENSE_REF + "-changed", False),
                ("LicenseRef-Netzwerkpunkt-Personal-Use-2.0", False),
                ("SEE LICENSE IN ../../LICENSE", True),
                ("SEE LICENSE IN LICENSE", False),
            ]:
                with self.subTest(value=value):
                    manifest.write_text(json.dumps({"license": value}))
                    self.assertEqual(not CHECK.check_package_json(root), accepted)
            (package / "LICENSE").write_bytes(b"different license\n")
            self.assertTrue(CHECK.check_package_json(root))
            (package / "LICENSE").write_bytes((root / "LICENSE").read_bytes())
            self.assertFalse(CHECK.check_package_json(root))

    def test_runtime_licenses_cannot_replace_native_product_copy(self):
        relative = "native/macos/scripts/build_app.py"
        original = ROOT / relative
        # Exercise the real AA recipe when present; other repos use its relevant shape.
        text = (
            original.read_text()
            if original.exists()
            else (
                "import shutil\n"
                'license_sources = list(prefix.glob("**/LICENSE*"))\n'
                'shutil.copy2(REPO / "LICENSE", resources / "LICENSE-AgentAuthority.txt")\n'
            )
        )
        lines = text.splitlines(keepends=True)
        copies = [
            node
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.Expr)
            and CHECK.native_product_license_copy(ast.get_source_segment(text, node))
        ]
        self.assertTrue(copies, "existing product copy must be covered")
        for node in copies:
            lines[node.lineno - 1 : node.end_lineno] = ["\n"] * (node.end_lineno - node.lineno + 1)
        mutated = "".join(lines)
        self.assertIn('prefix.glob("**/LICENSE*")', mutated)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe = root / relative
            recipe.parent.mkdir(parents=True)
            recipe.write_text(text)
            self.assertFalse(CHECK.check_packagers(root))
            recipe.write_text(mutated)
            self.assertTrue(CHECK.check_packagers(root))
            # A commented-out copy must not repair the missing product copy.
            recipe.write_text(
                mutated
                + '\n# shutil.copy2(REPO / "LICENSE", resources / "LICENSE-AgentAuthority.txt")\n'
            )
            self.assertTrue(CHECK.check_packagers(root))

    def test_existing_recipes_fail_when_product_inclusion_is_removed(self):
        for relative, proofs in CHECK.PACKAGER_PROOFS.items():
            original = ROOT / relative
            if not original.exists():
                continue
            text = original.read_text()
            with self.subTest(recipe=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                recipe = root / relative
                recipe.parent.mkdir(parents=True)
                recipe.write_text(text)
                self.assertFalse(CHECK.check_packagers(root))
                for proof in proofs:
                    with self.subTest(proof=proof):
                        self.assertIn(proof, text)
                        recipe.write_text(text.replace(proof, "REMOVED_PRODUCT_INCLUSION"))
                        self.assertTrue(CHECK.check_packagers(root))


if __name__ == "__main__":
    unittest.main()
