"""Offline delivery and execution of the reusable workflow's actual verifier."""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "PluginRuntime/plugin_runtime.py"
WORKFLOW = ROOT / ".github/workflows/plugin-runtime.yml"


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.authority = self.root / "standards"
        self.script = self.authority / "scripts/plugin-runtime.py"
        self.canonical = self.authority / "PluginRuntime/plugin_runtime.py"
        self.workflow = self.authority / ".github/workflows/plugin-runtime.yml"
        for source, target in (
            (ROOT / "scripts/plugin-runtime.py", self.script),
            (CANONICAL, self.canonical),
            (WORKFLOW, self.workflow),
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.checkout = self.root / "plugin checkout"
        self.checkout.mkdir()
        self.target = self.checkout / "bin/plugin_runtime.py"

    def run_command(self, *args, expected=0):
        result = subprocess.run(
            [sys.executable, "-I", str(self.script), *map(str, args)],
            cwd=self.checkout, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def test_sync_and_check_from_another_directory_with_spaces(self):
        self.run_command("sync", self.checkout)
        self.assertEqual(self.target.read_bytes(), self.canonical.read_bytes())
        before = self.target.stat().st_mtime_ns
        self.run_command("check", self.checkout)
        self.assertEqual(self.target.stat().st_mtime_ns, before)

    def test_sync_replaces_drift_and_can_be_repeated(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b"local copy\n")
        self.run_command("sync", self.checkout)
        self.run_command("sync", self.checkout)
        self.assertEqual(self.target.read_bytes(), self.canonical.read_bytes())

    def test_check_rejects_missing_file_without_writing(self):
        result = self.run_command("check", self.checkout, expected=1)
        self.assertIn("Missing plugin runtime", result.stderr)
        self.assertFalse(self.target.parent.exists())

    def test_check_rejects_byte_drift_without_writing(self):
        self.run_command("sync", self.checkout)
        for content in (self.canonical.read_bytes() + b"\n", b"\xff\x00"):
            with self.subTest(content=content[-8:]):
                self.target.write_bytes(content)
                result = self.run_command("check", self.checkout, expected=1)
                self.assertIn("differs from the canonical", result.stderr)
                self.assertEqual(self.target.read_bytes(), content)

    def test_commands_require_an_existing_checkout_directory(self):
        invalid = self.root / "missing"
        for command in ("sync", "check"):
            with self.subTest(command=command):
                self.run_command(command, invalid, expected=1)
                self.assertFalse(invalid.exists())
                self.run_command(command, self.script, expected=1)

    def test_delivery_cannot_follow_symlinks_outside_checkout(self):
        outside = self.root / "outside"
        outside.mkdir()
        protected = outside / "plugin_runtime.py"
        protected.write_bytes(b"outside content\n")
        for parent_link in (True, False):
            with self.subTest(parent_link=parent_link):
                if parent_link:
                    self.target.parent.symlink_to(outside, target_is_directory=True)
                else:
                    self.target.parent.mkdir()
                    self.target.symlink_to(protected)
                for command in ("sync", "check"):
                    result = self.run_command(command, self.checkout, expected=1)
                    self.assertIn("escapes the checkout", result.stderr)
                    self.assertEqual(protected.read_bytes(), b"outside content\n")
                if parent_link:
                    self.target.parent.unlink()
                else:
                    self.target.unlink()
                    self.target.parent.rmdir()

    def test_check_workflow_matches_canonical(self):
        self.run_command("check-workflow")

    def test_check_workflow_rejects_a_stale_digest(self):
        self.canonical.write_bytes(self.canonical.read_bytes() + b"\n")
        result = self.run_command("check-workflow", expected=1)
        self.assertIn("differs from the canonical runtime", result.stderr)

    def test_check_workflow_rejects_missing_malformed_and_duplicate_digest(self):
        original = self.workflow.read_text()
        line = next(line for line in original.splitlines() if "PLUGIN_RUNTIME_SHA256:" in line)
        for replacement in ("", "          PLUGIN_RUNTIME_SHA256: 'bad'", line + "\n" + line):
            with self.subTest(replacement=replacement):
                self.workflow.write_text(original.replace(line, replacement))
                result = self.run_command("check-workflow", expected=1)
                self.assertIn("exactly one quoted", result.stderr)


class WorkflowVerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "consumer"
        self.checkout.mkdir()
        self.target = self.checkout / "bin/plugin_runtime.py"
        self.target.parent.mkdir()
        workflow = WORKFLOW.read_text()
        self.command = [sys.executable, "-I", str(ROOT / "scripts/plugin-runtime.py"), "check", str(self.checkout)]
        self.digest = re.search(r"PLUGIN_RUNTIME_SHA256: '([0-9a-f]{64})'", workflow).group(1)

    def verify(self, expected):
        result = subprocess.run(
            self.command, text=True,
            cwd=self.checkout, capture_output=True, timeout=10,
            env=dict(os.environ, PLUGIN_RUNTIME_SHA256=self.digest),
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def test_exact_runtime_passes(self):
        self.target.write_bytes(CANONICAL.read_bytes())
        self.verify(0)

    def test_missing_runtime_fails(self):
        result = self.verify(1)
        self.assertIn("Missing plugin runtime", result.stderr)

    def test_changed_runtime_fails_without_executing_consumer_code(self):
        marker = self.checkout / "executed"
        self.target.write_text("from pathlib import Path\nPath('executed').touch()\n")
        result = self.verify(1)
        self.assertIn("differs from the canonical", result.stderr)
        self.assertFalse(marker.exists())

    def test_changed_runtime_fails_with_consumer_hashlib(self):
        self.target.write_bytes(CANONICAL.read_bytes() + b"\n")
        (self.checkout / "hashlib.py").write_text(textwrap.dedent("""\
            import os
            from pathlib import Path

            Path("hashlib-imported").touch()

            class Digest:
                def hexdigest(self):
                    return os.environ["PLUGIN_RUNTIME_SHA256"]

            def sha256(data):
                return Digest()
            """))
        result = self.verify(1)
        self.assertIn("differs from the canonical", result.stderr)
        self.assertFalse((self.checkout / "hashlib-imported").exists())

    def test_runtime_outside_checkout_fails_even_when_digest_matches(self):
        outside = self.root / "outside.py"
        outside.write_bytes(CANONICAL.read_bytes())
        self.assertEqual(hashlib.sha256(outside.read_bytes()).hexdigest(), self.digest)
        self.target.symlink_to(outside)
        self.verify(1)


if __name__ == "__main__":
    unittest.main()
