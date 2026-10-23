import contextlib
import importlib.util
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parent.parent / "actions/notify-catalog/notify.py"
spec = importlib.util.spec_from_file_location("catalog_notification", SCRIPT)
notification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notification)
TOKEN = "fixture-token-never-a-real-credential"
RUN = {
    "workflow_run_id": 123,
    "run_url": "https://api.github.com/repos/computer-mcp/computer-mcp.github.io/actions/runs/123",
    "html_url": "https://github.com/computer-mcp/computer-mcp.github.io/actions/runs/123",
}


class Response(io.BytesIO):
    def __init__(self, body=None, status=200):
        super().__init__(json.dumps(RUN).encode() if body is None else body)
        self.status = status


def failure(status, headers=None):
    return urllib.error.HTTPError(notification.ENDPOINT, status, TOKEN, headers or {}, io.BytesIO(TOKEN.encode()))


class NotificationTests(unittest.TestCase):
    def test_dispatch_uses_only_fixed_central_ref_and_returns_validated_run(self):
        response = Response()
        opener = Mock()
        opener.open.return_value = response
        self.assertEqual(notification.notify(TOKEN, opener=opener), RUN["html_url"])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, notification.ENDPOINT)
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"ref": "master"})
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(request.get_header("X-github-api-version"), "2026-03-10")
        self.assertLessEqual(opener.open.call_args.kwargs["timeout"], 20)
        self.assertTrue(response.closed)

    def test_invalid_credentials_do_not_start_requests(self):
        for token in ("", " ", "with\nnewline", "with\rreturn", "é", "a" * 8193):
            with self.subTest(token_length=len(token)):
                opener = Mock()
                with self.assertRaises(notification.NotificationError):
                    notification.notify(token, opener=opener)
                opener.open.assert_not_called()

    def test_untrusted_run_identity_is_not_reported_as_success(self):
        for changes in ({"workflow_run_id": True}, {"workflow_run_id": 0},
                        {"workflow_run_id": 9007199254740992}, {"workflow_run_id": "123"},
                        {"run_url": "https://example.invalid/123"},
                        {"html_url": "https://github.com/another/repo/actions/runs/123"}):
            with self.subTest(changes=changes):
                response = Response(json.dumps({**RUN, **changes}).encode())
                opener = Mock()
                opener.open.return_value = response
                with self.assertRaisesRegex(notification.NotificationError, "identity"):
                    notification.notify(TOKEN, opener=opener)
                self.assertTrue(response.closed)

    def test_malformed_and_oversized_responses_fail_without_body_disclosure(self):
        for body in (TOKEN.encode(), b"[]", b"\xff", b"x" * (notification.MAX_RESPONSE + 1)):
            response = Response(body)
            opener = Mock()
            opener.open.return_value = response
            with self.assertRaises(notification.NotificationError) as error:
                notification.notify(TOKEN, opener=opener)
            self.assertNotIn(TOKEN, str(error.exception))
            self.assertTrue(response.closed)

    def test_response_without_run_receipt_is_not_deployment_evidence(self):
        opener = Mock()
        opener.open.return_value = Response(b"", status=204)
        with self.assertRaisesRegex(notification.NotificationError, "accepted run"):
            notification.notify(TOKEN, opener=opener)

    def test_transient_failure_retries_idempotent_reconciliation(self):
        opener, sleep = Mock(), Mock()
        failed = failure(503)
        opener.open.side_effect = [failed, Response()]
        self.assertEqual(notification.notify(TOKEN, opener=opener, sleep=sleep), RUN["html_url"])
        self.assertTrue(failed.closed)
        sleep.assert_called_once_with(1)
        self.assertEqual(opener.open.call_count, 2)

    def test_server_retry_delay_is_respected(self):
        for status, headers in ((429, {"Retry-After": "5"}),
                                (403, {"X-RateLimit-Remaining": "0", "Retry-After": "5"})):
            opener, sleep = Mock(), Mock()
            opener.open.side_effect = [failure(status, headers), Response()]
            self.assertEqual(notification.notify(TOKEN, opener=opener, sleep=sleep), RUN["html_url"])
            sleep.assert_called_once_with(5)

    def test_long_or_invalid_retry_delay_is_not_ignored(self):
        for value in ("31", "1000", "tomorrow", "-1", "١"):
            opener, sleep = Mock(), Mock()
            opener.open.side_effect = failure(429, {"Retry-After": value})
            with self.assertRaises(notification.NotificationError):
                notification.notify(TOKEN, opener=opener, sleep=sleep)
            self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_rate_limit_without_explicit_delay_never_retries_early(self):
        for status in (403, 429):
            with self.subTest(status=status):
                opener, sleep = Mock(), Mock()
                opener.open.side_effect = [failure(status, {"X-RateLimit-Remaining": "0",
                                                            "X-RateLimit-Reset": "9999999999"}), Response()]
                with self.assertRaises(notification.NotificationError):
                    notification.notify(TOKEN, opener=opener, sleep=sleep)
                self.assertEqual(opener.open.call_count, 1)
                sleep.assert_not_called()

    def test_authentication_and_configuration_failures_are_not_retried(self):
        for status in (400, 401, 403, 404, 422):
            opener, sleep = Mock(), Mock()
            opener.open.side_effect = failure(status)
            with self.assertRaisesRegex(notification.NotificationError, f"HTTP {status}"):
                notification.notify(TOKEN, opener=opener, sleep=sleep)
            self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_network_retry_limit(self):
        for failure in (urllib.error.URLError(TOKEN), http.client.IncompleteRead(TOKEN.encode()),
                        http.client.RemoteDisconnected(TOKEN)):
            opener, sleep = Mock(), Mock()
            opener.open.side_effect = failure
            with self.assertRaises(notification.NotificationError) as error:
                notification.notify(TOKEN, opener=opener, sleep=sleep)
            self.assertNotIn(TOKEN, str(error.exception))
            self.assertEqual(opener.open.call_count, 3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_elapsed_budget_prevents_retry(self):
        elapsed = [0]
        opener, sleep = Mock(), Mock()

        def slow_request(*args, **kwargs):
            elapsed[0] = 89.5
            raise urllib.error.URLError(TOKEN)

        opener.open.side_effect = slow_request
        with self.assertRaises(notification.NotificationError):
            notification.notify(TOKEN, opener=opener, clock=lambda: elapsed[0], sleep=sleep)
        self.assertEqual(opener.open.call_count, 1)
        sleep.assert_not_called()

    def test_body_read_checks_elapsed_budget(self):
        response = Response()
        with self.assertRaisesRegex(notification.NotificationError, "time budget"):
            notification.accepted_run(response, 90, lambda: 91)

    def test_actual_http_redirects_never_receive_forwarded_credentials(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                observed.append(self.path)
                self.send_response(int(self.path[1:]))
                self.send_header("Location", "/credential-sink")
                self.end_headers()

            def do_GET(self):
                observed.append(self.path)
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for status in (301, 302, 303, 307, 308):
                with patch.object(notification, "ENDPOINT", f"http://127.0.0.1:{server.server_port}/{status}"):
                    with self.assertRaises(notification.NotificationError):
                        notification.notify(TOKEN)
            self.assertEqual(observed, [f"/{status}" for status in (301, 302, 303, 307, 308)])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(5)
        self.assertFalse(worker.is_alive())

    def test_action_outputs_only_accepted_run_and_distinguishes_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            stdout = io.StringIO()
            with patch.dict(os.environ, {"CATALOG_DISPATCH_TOKEN": TOKEN, "GITHUB_OUTPUT": str(output)}):
                with patch.object(notification, "notify", return_value=RUN["html_url"]), contextlib.redirect_stdout(stdout):
                    notification.main()
            self.assertEqual(output.read_text(), "run-url=" + RUN["html_url"] + "\n")
            self.assertIn("does not prove", stdout.getvalue())
            self.assertNotIn(TOKEN, stdout.getvalue())

    def test_actual_command_missing_credential_fails_without_traceback(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                timeout=5, env={**os.environ, "CATALOG_DISPATCH_TOKEN": ""})
        self.assertEqual(result.returncode, 1)
        self.assertIn("CATALOG_DISPATCH_TOKEN", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_command_does_not_disclose_transport_error(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError(TOKEN)
        stderr = io.StringIO()
        with patch.dict(os.environ, {"CATALOG_DISPATCH_TOKEN": TOKEN}):
            with patch.object(notification.urllib.request, "build_opener", return_value=opener):
                with patch.object(notification.time, "sleep"), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as error:
                        notification.main()
        self.assertEqual(error.exception.code, 1)
        self.assertNotIn(TOKEN, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
