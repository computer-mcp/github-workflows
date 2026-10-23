#!/usr/bin/env python3
"""Validate YAML structure, immutable action references and workflow boundaries."""

from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


class UniqueLoader(yaml.BaseLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(f"duplicate YAML key: {key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def read(path):
    return yaml.load(path.read_text(), Loader=UniqueLoader)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_uses(value):
    if isinstance(value, dict):
        if "uses" in value:
            use = value["uses"]
            require(use.startswith("./") or re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", use), "action/workflow must use a full SHA: " + use)
        for item in value.values():
            check_uses(item)
    elif isinstance(value, list):
        for item in value:
            check_uses(item)


def validate(root=ROOT):
    workflows = sorted((root / ".github/workflows").glob("*.yml"))
    require(bool(workflows), "no workflows found")
    for path in workflows:
        document = read(path)
        require(isinstance(document, dict) and {"name", "on", "permissions", "jobs"} <= document.keys(), str(path) + ": invalid workflow")
        check_uses(document)
        for name, job in document["jobs"].items():
            require(isinstance(job, dict), name + ": expected a job mapping")
            require(("uses" in job) != ("steps" in job), name + ": expected reusable call or steps")
            if "steps" not in job:
                continue
            require("runs-on" in job and isinstance(job["steps"], list), name + ": missing runner/steps")
            for step in job["steps"]:
                require(isinstance(step, dict) and (("uses" in step) != ("run" in step)), name + ": invalid step")
                require("<<'PY'" not in step.get("run", ""), name + ": scripts belong in scripts/")
            if "workflow_call" in document["on"] and not (path.name == "plugin-release.yml" and name == "build"):
                require(any(step.get("with", {}).get("ref") == "${{ job.workflow_sha }}" and
                            step.get("with", {}).get("repository") == "${{ job.workflow_repository }}"
                            for step in job["steps"]), name + ": shared implementation checkout must use job.workflow_sha")
    for path in (root / "actions").glob("*/action.yml"):
        document = read(path)
        check_uses(document)
        require(document["runs"]["using"] == "composite", str(path) + ": expected composite action")
        require(all("run" not in step or "shell" in step for step in document["runs"]["steps"]), "composite run steps need shells")
    release = read(root / ".github/workflows/plugin-release.yml")
    require("concurrency" not in release, "release must preserve queued runs")
    require("cache" not in (root / ".github/workflows/plugin-release.yml").read_text().lower(), "release must not use caches")
    policy = read(root / ".github/workflows/source-policy.yml")
    ci = read(root / ".github/workflows/ci.yml")
    require("edited" in policy["on"]["pull_request"]["types"], "policy must rerun for title edits")
    require("edited" not in ci["on"]["pull_request"]["types"], "title edits must not replace validation")
    require(policy["jobs"]["policy"]["uses"] == "./.github/workflows/policy.yml", "repository PRs must use source policy")
    aggregate = ci["jobs"]["validate"]
    require(aggregate["if"] == "always()" and aggregate["with"]["needs-json"] == "${{ toJSON(needs) }}",
            "validation aggregate must inspect all dependency results")
    return workflows


def main():
    try:
        workflows = validate()
        print("PASS YAML structure, full pins and workflow boundaries")
        if executable := shutil.which("actionlint"):
            # actionlint 1.7.12 predates GitHub's documented job workflow identity.
            # Limit compatibility filtering to those exact properties; other
            # expression and shell errors remain fatal.
            subprocess.run([executable, "-ignore", r'property "workflow_(repository|sha|ref|file_path)" is not defined in object type',
                            *map(str, workflows)], check=True)
            print("PASS actionlint (documented job.workflow_* compatibility filter)")
        else:
            print("actionlint unavailable; Python YAML and contract validation completed")
        return 0
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, subprocess.SubprocessError) as error:
        print("FAIL workflows: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
