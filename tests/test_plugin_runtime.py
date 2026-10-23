"""Version assertions are resolved before the owned native probe starts."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PluginRuntime"))
import plugin_runtime as runtime


class VersionTests(unittest.TestCase):
    def test_tree_assertion_preserves_exact_stdout(self):
        tree = {"executable_checks": [
            {"args": ["--help"], "stdout": "help\n"},
            {"args": ["--version"], "stdout": "native 1.0\n"},
            {"args": ["--version"], "stdout": "later\n"},
        ]}
        self.assertEqual(runtime.expected_version(tree), "native 1.0\n")

    def test_empty_stdout_is_an_assertion(self):
        self.assertEqual(runtime.expected_version({
            "executable_checks": [{"args": ["--version"], "stdout": ""}],
        }), "")

    def test_missing_assertion_fails_before_any_process_starts(self):
        for tree in (
            {},
            {"executable_checks": []},
            {"executable_checks": [{"args": ["--help"], "stdout": "help\n"}]},
            {"executable_checks": [{"args": ["--version", "extra"], "stdout": "1\n"}]},
            {"executable_checks": [{"args": ["--version"]}]},
            {"executable_checks": [{"args": ["--version"], "stdout": None}]},
        ):
            with self.subTest(tree=tree), patch.object(runtime, "Process") as process:
                with self.assertRaises(runtime.Failure) as raised:
                    runtime.verify_version("/native", runtime.expected_version(tree), runtime.Job(), "/work")
                self.assertEqual(raised.exception.code, "invalid_configuration")
                self.assertEqual(str(raised.exception), "Package lacks its native version assertion")
                process.assert_not_called()

    def test_tree_and_direct_version_strings_use_the_same_probe(self):
        expected = "native α\n"
        tree = {"executable_checks": [{"args": ["--version"], "stdout": expected}]}
        for value in (runtime.expected_version(tree), expected):
            with self.subTest(value=value):
                process = Mock()
                process.read.side_effect = [b"native ", "α\n".encode(), None]
                process.finish.return_value = 0
                retained = Mock()
                job = runtime.Job()
                with patch.object(runtime, "Process", return_value=process) as factory:
                    runtime.verify_version("/native", value, job, "/work", retained)
                factory.assert_called_once_with(["/native", "--version"], "/work")
                retained.assert_called_once_with(process)
                process.end_input.assert_called_once_with()
                deadline = process.read.call_args_list[0].args[0]
                for call in process.read.call_args_list:
                    self.assertEqual(call.args, (deadline, job))
                process.finish.assert_called_once_with(deadline, job)
                process.close.assert_called_once_with()

    def test_mismatch_and_nonzero_exit_keep_the_existing_failure(self):
        for output, status in ((b"other\n", 0), (b"native", 0), (b"native\n", 1)):
            with self.subTest(output=output, status=status):
                process = Mock()
                process.read.side_effect = [output, None]
                process.finish.return_value = status
                with patch.object(runtime, "Process", return_value=process):
                    with self.assertRaises(runtime.Failure) as raised:
                        runtime.verify_version("/native", "native\n", runtime.Job(), "/work")
                self.assertEqual(raised.exception.code, "incompatible_vendor")
                self.assertEqual(str(raised.exception), "Vendor version differs from the verified plugin baseline")
                process.close.assert_called_once_with()

    def test_output_bound_closes_the_probe(self):
        process = Mock()
        process.read.side_effect = [b"x" * 65536, b"x"]
        with patch.object(runtime, "Process", return_value=process):
            with self.assertRaises(runtime.Failure) as raised:
                runtime.verify_version("/native", "native\n", runtime.Job(), "/work")
        self.assertEqual(raised.exception.code, "incompatible_vendor")
        self.assertEqual(str(raised.exception), "Native version output exceeded its bound")
        process.finish.assert_not_called()
        process.close.assert_called_once_with()

    def test_cancellation_and_timeout_close_the_probe(self):
        for code in ("cancelled", "timeout"):
            with self.subTest(code=code):
                failure = runtime.Failure(code, "probe stopped")
                process = Mock()
                process.read.side_effect = failure
                with patch.object(runtime, "Process", return_value=process):
                    with self.assertRaises(runtime.Failure) as raised:
                        runtime.verify_version("/native", "native\n", runtime.Job(), "/work")
                self.assertIs(raised.exception, failure)
                process.close.assert_called_once_with()

    def test_retention_failure_still_closes_the_probe(self):
        process = Mock()
        failure = RuntimeError("adapter shutdown")
        with patch.object(runtime, "Process", return_value=process):
            with self.assertRaises(RuntimeError) as raised:
                runtime.verify_version("/native", "native\n", runtime.Job(), "/work", Mock(side_effect=failure))
        self.assertIs(raised.exception, failure)
        process.end_input.assert_not_called()
        process.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
