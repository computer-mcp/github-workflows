#!/usr/bin/env python3
"""Enforce the source rules from the requested Computer MCP declaration."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import declaration
from github_api import Fixture, GitHub, Unavailable


ZERO = "0" * 40
PRIVATE_PATH = re.compile(r"/(?:Users|home)/[\w. -]+(?:/|(?=[\s`\"')]|$))|"
                          r"[A-Za-z]:[\\/]Users[\\/][\w. -]+(?:[\\/]|(?=[\s`\"')]|$))")
TASK_REFERENCE = re.compile(r"(?<![\w.-])[.]agent[/\\][^\s`\"'<>]+")
TOOLS = re.compile(r"^(?:claude|codex|chatgpt|(?:github )?copilot|cursor|aider|gemini|AI)"
                   r"(?: (?:code|bot|assistant|agent))?\s*(?:<|$)|<(?:noreply|bot)@(?:anthropic|openai)[.]com>", re.I)
ATTRIBUTION = re.compile(r"^\s*(?:[#*>/-]+\s*)?(?:[\U0001f300-\U0001faff]\s*)?"
                         r"(generated[- ](?:by|with):|generated (?:by|with) |"
                         r"(?:co-authored-by|assisted-by|powered-by|made-with|signed-off-by):)\s*(.*)", re.I | re.M)


def attribution(text):
    for match in ATTRIBUTION.finditer(text):
        kind = match[1].lower()
        # Generation statements identify provenance. Co-authors and sign-offs
        # identify people too, so only tool/bot identities are rejected there.
        if (kind.startswith(("generated", "assisted", "powered", "made")) or TOOLS.search(match[2])
                or (kind.startswith("co-authored") and "[bot]" in match[2].lower())):
            return True
    return False


def content_findings(label, text, *, path=False):
    findings = []
    if PRIVATE_PATH.search(text):
        findings.append(f"{label}: private machine path")
    if TASK_REFERENCE.search(text) or (path and ".agent" in Path(text).parts):
        findings.append(f"{label}: reference to local task state")
    if attribution(text):
        findings.append(f"{label}: tool or agent attribution")
    return findings


def message_findings(label, message, policy):
    subject = message.split("\n", 1)[0]
    types = "|".join(re.escape(value) for value in policy["types"])
    pattern = rf"(?:{types})(?:\([^()\r\n]+\))?!?: \S[^\r\n]*"
    findings = []
    if not re.fullmatch(pattern, subject) or subject.rstrip() != subject:
        findings.append(f"{label}: expected a Conventional Commit subject")
    findings += content_findings(label, message)
    return findings


def commit_findings(sha, record, policy):
    details = record.get("commit") or {}
    identity = details.get("committer") or {}
    account = record.get("committer") or {}
    verification = details.get("verification") or {}
    findings = []
    if record.get("sha") != sha or verification.get("verified") is not True or verification.get("reason") != "valid":
        findings.append(f"{sha}: commit is not verified by GitHub")
    owner = (identity.get("name") == policy["owner"] and identity.get("email") == policy["email"]
             and account.get("login", "").lower() == policy["owner"].lower())
    github = (identity.get("name") == "GitHub" and identity.get("email") == "noreply@github.com"
              and account.get("login") == "web-flow")
    if not (owner or github):
        findings.append(f"{sha}: committer must be GitHub or the declared owner")
    if owner and not (verification.get("signature") or "").startswith("-----BEGIN SSH SIGNATURE-----"):
        findings.append(f"{sha}: owner commit must be SSH-signed")
    return findings


def git(root, *args, binary=False):
    result = subprocess.check_output(["git", "-C", str(root), *args], stdin=subprocess.DEVNULL)
    return result if binary else result.decode("utf-8", errors="replace")


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value) or value == ZERO:
        raise ValueError("policy requires full, nonzero source commit SHAs")
    return value


def added_findings(patch, path):
    findings, number = [], None
    for line in patch.split("\n"):
        if match := re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line):
            number = int(match[1])
        elif number is not None and line.startswith("+"):
            findings += content_findings(f"{path}:{number}", line[1:])
            number += 1
        elif number is not None and line.startswith(" "):
            number += 1
    return findings


def check(root, event, event_name, policy, api):
    findings = []
    default_push = False
    if event_name == "pull_request":
        pr = event["pull_request"]
        head, base = sha(pr["head"]["sha"]), sha(pr["base"]["sha"])
        title = pr["title"]
        if "\n" in title or "\r" in title:
            findings.append("PR title: expected one line")
        findings += message_findings("PR title", title, policy)
        comparison = git(root, "merge-base", base, head).strip()
    elif event_name == "merge_group":
        head, base = sha(event["merge_group"]["head_sha"]), sha(event["merge_group"]["base_sha"])
        comparison = base
    elif event_name == "push":
        if event.get("deleted"):
            print("PASS source policy: branch deletion has no added content")
            return []
        head = sha(event["after"])
        base = event["before"]
        if base == ZERO:
            base = None
            comparison = git(root, "hash-object", "-t", "tree", "--stdin", binary=False).strip()
        else:
            comparison = sha(base)
        default_push = event["ref"] == "refs/heads/" + event["repository"]["default_branch"]
    else:
        raise ValueError("policy requires pull_request, merge_group or push")
    commits = [head] if base is None else git(root, "rev-list", "--reverse", base + ".." + head).splitlines()
    # The queue's temporary merge commits are not accepted default-branch commits.
    if event_name != "merge_group":
        for commit in commits:
            message = git(root, "show", "-s", "--format=%B", commit)
            findings += message_findings(commit, message, policy)
            if default_push:
                repository = event["repository"]["full_name"]
                if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
                    raise ValueError("invalid repository identity")
                findings += commit_findings(commit, api.get(f"repos/{repository}/commits/{commit}"), policy)
    paths = git(root, "diff", "--name-only", "--no-renames", "--diff-filter=ACMT", "-z", comparison, head, "--").split("\0")
    for path in filter(None, paths):
        findings += content_findings(path, path, path=True)
        if git(root, "--literal-pathspecs", "ls-tree", head, "--", path).startswith("160000 "):
            continue
        blob = git(root, "cat-file", "blob", head + ":" + path, binary=True)
        if b"\0" in blob[:8000]:
            continue
        patch = git(root, "--literal-pathspecs", "diff", "--text", "--no-ext-diff", "--no-textconv", "--no-color",
                    "--no-renames", "--unified=0", comparison, head, "--", path)
        findings += added_findings(patch, path)
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--declaration-root", type=Path, required=True)
    parser.add_argument("--declaration-revision", required=True)
    parser.add_argument("--event", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME"))
    parser.add_argument("--fixture", type=Path, help="Use offline GET responses and a fixture declaration")
    args = parser.parse_args(argv)
    try:
        text = declaration.revision(args.declaration_root, args.declaration_revision, offline=bool(args.fixture))
        policy = declaration.source_policy(text)
        if not args.event:
            raise ValueError("event file is required")
        api = Fixture(args.fixture) if args.fixture else GitHub()
        findings = check(args.root, json.loads(Path(args.event).read_text()), args.event_name, policy, api)
        for finding in findings:
            print("FAIL " + " ".join(finding.splitlines()))
        if not findings:
            print("PASS source policy")
        return int(bool(findings))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("FAIL policy could not complete: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
