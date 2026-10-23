#!/usr/bin/env python3
"""Request the official catalog workflow without supplying catalog metadata."""

import json
import http.client
import os
import sys
import time
import urllib.error
import urllib.request


REPOSITORY = "computer-mcp/computer-mcp.github.io"
ENDPOINT = f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/pages.yml/dispatches"
MAX_RESPONSE = 16384


class NotificationError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        fp.close()
        raise NotificationError("Catalog notification refuses HTTP redirects")


def accepted_run(response, deadline, clock):
    if response.status != 200:
        raise NotificationError("Catalog notification did not return an accepted run")
    data = bytearray()
    while True:
        if clock() >= deadline:
            raise NotificationError("Catalog notification response exceeded its time budget")
        chunk = response.read1(min(4096, MAX_RESPONSE + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_RESPONSE:
            raise NotificationError("Catalog notification response exceeded its byte budget")
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError):
        raise NotificationError("Catalog notification returned invalid JSON") from None
    run_id = result.get("workflow_run_id") if isinstance(result, dict) else None
    if (type(run_id) is not int or not 0 < run_id <= 9007199254740991
            or result.get("run_url") != f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}"
            or result.get("html_url") != f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"):
        raise NotificationError("Catalog notification returned an invalid run identity")
    return result["html_url"]


def notify(token, *, opener=None, clock=time.monotonic, sleep=time.sleep):
    if not token or len(token) > 8192 or any(not 33 <= ord(c) <= 126 for c in token):
        raise NotificationError("CATALOG_DISPATCH_TOKEN is missing or invalid; check the catalog App token step")
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = clock() + 90
    for attempt in range(3):
        remaining = deadline - clock()
        if remaining <= 0:
            raise NotificationError("Catalog notification exhausted its retry budget")
        request = urllib.request.Request(ENDPOINT, data=b'{"ref":"master"}', method="POST", headers={
            "Accept": "application/vnd.github+json", "Content-Type": "application/json",
            "Authorization": "Bearer " + token, "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "computer-mcp-catalog-notification",
        })
        delay = 2 ** attempt
        try:
            with opener.open(request, timeout=min(20, remaining)) as response:
                return accepted_run(response, deadline, clock)
        except urllib.error.HTTPError as error:
            with error:
                rate_limited = error.code == 403 and error.headers.get("X-RateLimit-Remaining") == "0"
                if error.code not in (429, 500, 502, 503, 504) and not rate_limited:
                    raise NotificationError(f"Catalog notification rejected (HTTP {error.code})") from None
                retry_after = error.headers.get("Retry-After")
                if retry_after is None and (error.code == 429 or rate_limited):
                    raise NotificationError("Catalog notification is rate limited; wait for the server cooldown before retrying") from None
                if retry_after is not None:
                    if not retry_after.isascii() or not retry_after.isdigit() or len(retry_after) > 2:
                        raise NotificationError("Catalog notification cannot honor the server retry delay") from None
                    delay = max(delay, int(retry_after))
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            # A lost response may have accepted the request. Central reconciliation is idempotent.
            pass
        if attempt == 2 or delay > 30 or clock() + delay >= deadline:
            raise NotificationError("Catalog notification failed within its retry budget; retry the workflow later")
        sleep(delay)
    raise AssertionError("Unreachable notification state")


def main():
    try:
        url = notify(os.environ.get("CATALOG_DISPATCH_TOKEN", ""))
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a", encoding="utf-8") as file:
                file.write(f"run-url={url}\n")
        print(f"Catalog reconciliation accepted: {url}")
        print("Acceptance does not prove catalog verification or Pages deployment; inspect the central run.")
    except (NotificationError, OSError, ValueError) as error:
        message = str(error) if isinstance(error, NotificationError) else type(error).__name__
        print(f"Catalog notification failed: {message}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
