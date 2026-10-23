"""GET-only GitHub observations, with the same interface for offline fixtures."""

import json
from pathlib import Path
import re
import subprocess


class Unavailable(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class GitHub:
    def get(self, path):
        if not re.match(r"^(repos|orgs|user/installations)/", path) or ".." in path:
            raise ValueError("Invalid GitHub API path")
        try:
            result = subprocess.run(["gh", "api", "--method", "GET", path,
                                     "-H", "Accept: application/vnd.github+json"],
                                    capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            raise Unavailable(f"GET {path}: request unavailable") from None
        if result.returncode:
            raise Unavailable(f"GET {path}: unavailable; check read permissions and resource existence")
        try:
            return json.loads(result.stdout, object_pairs_hook=unique_object)
        except ValueError:
            raise Unavailable(f"GET {path}: invalid JSON") from None

    def collection(self, path, key=None):
        result = []
        for page in range(1, 10001):
            separator = "&" if "?" in path else "?"
            value = self.get(f"{path}{separator}per_page=100&page={page}")
            batch = value.get(key) if key and isinstance(value, dict) else value if key is None else None
            if not isinstance(batch, list):
                raise Unavailable(f"GET {path}: invalid collection")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise Unavailable(f"GET {path}: pagination limit exceeded")


class Fixture(GitHub):
    def __init__(self, path):
        self.responses = json.loads(Path(path).read_text(), object_pairs_hook=unique_object)

    def get(self, path):
        if path not in self.responses:
            raise Unavailable(f"GET {path}: absent from offline fixture")
        return self.responses[path]
