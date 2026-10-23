#!/usr/bin/env python3
"""Execute the release helper checked out with this job's workflow revision."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys


def run(stage):
    helper = Path(__file__).resolve().with_name("plugin_release.py")
    if helper.is_symlink() or hashlib.sha256(helper.read_bytes()).hexdigest() != os.environ["PLUGIN_RELEASE_SHA256"]:
        raise ValueError("Release helper differs from this workflow pin")
    root = Path(os.environ["RUNNER_TEMP"]) / "plugin-release"
    arguments = [sys.executable, "-I", str(helper), "resolve" if stage == "source" else stage,
                 "--repository", os.environ["GH_REPOSITORY"]]
    if stage == "source":
        revision = os.environ["RELEASE_WORKFLOW_SHA"]
        reference = os.environ["RELEASE_WORKFLOW_REF"]
        prefix = "computer-mcp/github-workflows/.github/workflows/plugin-release.yml@"
        if not re.fullmatch("[0-9a-f]{40}", revision) or reference != prefix + revision:
            raise ValueError("Pin the reusable release workflow by its full commit SHA")
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"workflow_ref={reference}\nworkflow_sha={revision}\n")
    if stage in {"source", "verify"}:
        arguments += ["--ref", os.environ["RELEASE_REF"], "--publish", os.environ["RELEASE_PUBLISH"]]
    if stage == "verify":
        for flag, variable in (("commit", "RELEASE_COMMIT"), ("build-artifact-id", "RELEASE_BUILD_ARTIFACT_ID"),
                               ("run-id", "GH_RUN_ID"), ("ci-artifact", "RELEASE_CI_ARTIFACT"),
                               ("workflow-ref", "RELEASE_WORKFLOW_REF"), ("workflow-sha", "RELEASE_WORKFLOW_SHA")):
            arguments += ["--" + flag, os.environ[variable]]
        arguments += ["--output", str(root / "assets")]
    if stage == "publish":
        arguments += ["--directory", str(root / "assets"), "--asset-digests", os.environ["RELEASE_ASSET_DIGESTS"]]
    subprocess.run(arguments, check=True)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"source", "verify", "publish"}:
            raise ValueError("Expected source, verify or publish")
        run(sys.argv[1])
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
