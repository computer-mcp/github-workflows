import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/resolve-terminal-demo.py"
spec = importlib.util.spec_from_file_location("terminal_demo", SCRIPT)
terminal_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(terminal_demo)


class TerminalDemoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="terminal demo ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.artifact = self.root / "artifact"
        self.artifact.mkdir()

    def executable(self, name, mode=0o755):
        target = self.artifact / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/bin/sh\nprintf 'demo\\n'\n")
        target.chmod(mode)
        return target

    def archive(self, name="cli.tar.gz", members=None):
        target = self.artifact / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if members is None:
            member = tarfile.TarInfo("package/bin/cli")
            member.mode = 0o755
            members = [(member, b"#!/bin/sh\nprintf 'demo\\n'\n")]
        with tarfile.open(target, "w:gz") as bundle:
            for member, content in members:
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
        return target

    def test_executable_paths_and_globs_resolve_one_file(self):
        target = self.executable("bin/demo cli")
        for pattern in ("bin/demo cli", "bin/demo*", "**/demo*"):
            with self.subTest(pattern=pattern):
                self.assertEqual(terminal_demo.resolve(self.artifact, "", pattern), target)

    def test_executable_zero_and_multiple_matches_fail(self):
        with self.assertRaisesRegex(ValueError, "exactly one.*found 0"):
            terminal_demo.resolve(self.artifact, "", "bin/*")
        self.executable("bin/one")
        self.executable("bin/two")
        with self.assertRaisesRegex(ValueError, "exactly one.*found 2"):
            terminal_demo.resolve(self.artifact, "", "bin/*")

    def test_non_executable_and_directory_targets_fail(self):
        self.executable("bin/cli", mode=0o644)
        with self.assertRaisesRegex(ValueError, "executable permission"):
            terminal_demo.resolve(self.artifact, "", "bin/cli")
        with self.assertRaisesRegex(ValueError, "regular file"):
            terminal_demo.resolve(self.artifact, "", "bin")

    def test_absolute_and_parent_paths_fail_for_both_inputs(self):
        for pattern in ("/bin/cli", "../cli", "bin/../cli", "bin/../../cli",
                        "C:/bin/cli", "C:\\bin\\cli", "\\\\server\\share\\cli", "bin\\..\\cli"):
            for argument in ("archive", "executable"):
                with self.subTest(pattern=pattern, argument=argument):
                    args = {"archive": "", "executable": "cli", argument: pattern}
                    with self.assertRaisesRegex(ValueError, "relative path"):
                        terminal_demo.resolve(self.artifact, **args)

    def test_line_breaks_and_nul_are_rejected(self):
        for pattern in ("cli\noutput=value", "cli\routput=value", "cli\0"):
            with self.subTest(pattern=repr(pattern)):
                with self.assertRaisesRegex(ValueError, "relative path"):
                    terminal_demo.resolve(self.artifact, "", pattern)
        self.executable("cli\noutput=value")
        with self.assertRaisesRegex(ValueError, "line breaks"):
            terminal_demo.resolve(self.artifact, "", "cli*")

    def test_symlink_cannot_escape_artifact(self):
        outside = self.root / "outside"
        outside.write_text("#!/bin/sh\n")
        outside.chmod(0o755)
        (self.artifact / "cli").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "outside"):
            terminal_demo.resolve(self.artifact, "", "cli")
        (self.artifact / "external").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "outside"):
            terminal_demo.resolve(self.artifact, "", "external/outside")

    def test_archive_extracts_into_a_fresh_directory_and_preserves_mode(self):
        self.archive("packages/demo cli.tar.gz")
        self.executable("package/bin/cli", mode=0o644)
        first = terminal_demo.resolve(self.artifact, "packages/*.tar.gz", "package/bin/*")
        second = terminal_demo.resolve(self.artifact, "packages/*.tar.gz", "package/bin/cli")
        self.assertTrue(os.access(first, os.X_OK))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertNotEqual(first.parents[2], second.parents[2])
        self.assertEqual(first.parents[2].parent, self.root)
        self.assertFalse(first.is_relative_to(self.artifact))
        self.assertEqual(subprocess.check_output([str(first)], text=True), "demo\n")

    def test_archive_zero_and_multiple_matches_fail(self):
        with self.assertRaisesRegex(ValueError, "exactly one.*found 0"):
            terminal_demo.resolve(self.artifact, "*.tar.gz", "cli")
        self.archive("one.tar.gz")
        self.archive("two.tar.gz")
        with self.assertRaisesRegex(ValueError, "exactly one.*found 2"):
            terminal_demo.resolve(self.artifact, "*.tar.gz", "cli")

    def test_archive_must_be_a_regular_gzip_tar_file(self):
        self.archive("cli.zip")
        with self.assertRaisesRegex(ValueError, r"\.tar\.gz"):
            terminal_demo.resolve(self.artifact, "cli.zip", "cli")
        (self.artifact / "directory.tar.gz").mkdir()
        with self.assertRaisesRegex(ValueError, "regular file"):
            terminal_demo.resolve(self.artifact, "directory.tar.gz", "cli")
        (self.artifact / "broken.tar.gz").write_text("not a gzip archive")
        with self.assertRaises(tarfile.TarError):
            terminal_demo.resolve(self.artifact, "broken.tar.gz", "cli")

    def test_unsafe_archive_member_paths_fail(self):
        for name in ("../escaped", "/absolute", "package/../../escaped"):
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                self.archive(members=[(member, b"unsafe")])
                with self.assertRaisesRegex(ValueError, "relative path"):
                    terminal_demo.resolve(self.artifact, "cli.tar.gz", "cli")
        self.assertFalse((self.root / "escaped").exists())

    def test_archive_links_cannot_escape_extraction_directory(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            with self.subTest(kind=kind):
                member = tarfile.TarInfo("cli")
                member.type = kind
                member.linkname = "../outside"
                self.archive(members=[(member, b"")])
                with self.assertRaises(tarfile.FilterError):
                    terminal_demo.resolve(self.artifact, "cli.tar.gz", "cli")

    def test_cli_emits_only_a_resolved_path_or_a_failure(self):
        target = self.executable("bin/demo cli")
        command = [sys.executable, "-I", str(SCRIPT), "--artifact-dir", str(self.artifact),
                   "--executable", "bin/demo*"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(target) + "\n")
        self.assertEqual(result.stderr, "")
        target.chmod(0o644)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("FAIL terminal demo:", result.stderr)


if __name__ == "__main__":
    unittest.main()
