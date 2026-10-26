#!/usr/bin/env python3
"""Enforce the source rules from the requested Computer MCP declaration."""

import argparse
from fnmatch import fnmatchcase
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
# The agents CLI's instruction units, declaration and lock at the repository root
# are tracked repository guidance; everything else under .agent/ is local task state.
AGENT_FILES = {".agent/agents.json", ".agent/agents.resolved"}
AGENT_INSTRUCTIONS = ".agent/instructions/"
# Ignore rules for the whole directory name no task file.
AGENT_PATTERNS = {".agent/*", ".agent/**"}
NESTED_REFERENCE = re.compile(r"[\w.:/\\-][/\\]$")
TOOL_IDENTITIES = json.loads((Path(__file__).resolve().parents[1] / "data/attribution-tools.json").read_text())


def inventory_pattern(value, separator=r"[ \t]+"):
    return separator.join(re.escape(part) for part in re.split(r"[ \t]+", value))


TOOL_NAMES = re.compile(r"(?:" + "|".join(inventory_pattern(name) for name in TOOL_IDENTITIES["names"]) + r")\b", re.I)
TOOL_EMAILS = {email.casefold() for email in TOOL_IDENTITIES["emails"]}
ATTRIBUTION = re.compile(
    r"(?:\b(?:" + "|".join(inventory_pattern(phrase, r"(?:[ \t]+|-)")
                             for phrase in TOOL_IDENTITIES["phrases"]) +
    r")\b[ \t]*:?|" + "|".join(re.escape(prefix) for prefix in TOOL_IDENTITIES["prefixes"]) + r")[ \t]*",
    re.I,
)


def tool_identity(value, *, coauthor=False):
    emails = re.findall(r"[\w.+-]+@[\w.-]+", value)
    if coauthor and emails:
        return any(email.casefold() in TOOL_EMAILS for email in emails)
    # Markdown emphasis and links may wrap an attribution's named identity.
    value = re.sub(r"[`*_]", "", value.strip())
    value = re.sub(r"\[([^]\n]+)\]\([^\n)]*\)", r"\1", value)
    name = value.split("<", 1)[0].strip()
    if re.search(r"[\w-]+\[bot\](?=$|[\s<(.,;])", name, re.I):
        return True
    if any(email.casefold() in TOOL_EMAILS for email in emails):
        return True
    return bool(TOOL_NAMES.match(value))


def attribution(text):
    return any(tool_identity(text[match.end():].split("\n", 1)[0],
                             coauthor=match.group().lower().startswith("co-authored-by"))
               for match in ATTRIBUTION.finditer(text))


def parse_path_exceptions(value):
    patterns = tuple(line.strip() for line in value.splitlines() if line.strip())
    for pattern in patterns:
        if ("\\" in pattern or ":" in pattern or
                any(part in {"", ".", ".."} for part in pattern.split("/"))):
            raise ValueError("path exceptions must be repository-relative globs: " + pattern)
    return patterns


def task_state(reference, *, path=False):
    reference = reference.replace("\\", "/")
    if ".." in reference.split("/"):
        return True
    if not path:
        reference = reference.rstrip(".,;:)]")
        if reference in AGENT_PATTERNS:
            return False
    if reference in AGENT_FILES:
        return False
    if reference.startswith(AGENT_INSTRUCTIONS):
        return ".agent" in reference[len(AGENT_INSTRUCTIONS):].split("/")
    return True


def task_reference(text, *, path=False):
    if path and ".agent" in Path(text).parts:
        return task_state(text, path=True)
    # A reference inside a longer path, such as plugin/.agent/ or ../.agent/, is not
    # the repository's own guidance; a lone leading slash anchors an ignore rule.
    return any(NESTED_REFERENCE.search(text[:match.start()]) or task_state(match.group())
               for match in TASK_REFERENCE.finditer(text))


def content_findings(label, text, *, path=False, exempt_paths=False):
    findings = []
    if not exempt_paths:
        if PRIVATE_PATH.search(text):
            findings.append(f"{label}: private machine path")
        if task_reference(text, path=path):
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


def added_findings(patch, path, *, exempt_paths=False):
    findings, number = [], None
    for line in patch.split("\n"):
        if match := re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line):
            number = int(match[1])
        elif number is not None and line.startswith("+"):
            findings += content_findings(f"{path}:{number}", line[1:], exempt_paths=exempt_paths)
            number += 1
        elif number is not None and line.startswith(" "):
            number += 1
    return findings


def check(root, event, event_name, policy, api, *, path_exceptions=()):
    findings = []
    default_push = False
    if event_name == "pull_request":
        pr = event["pull_request"]
        head, base = sha(pr["head"]["sha"]), sha(pr["base"]["sha"])
        title = pr["title"]
        if "\n" in title or "\r" in title:
            findings.append("PR title: expected one line")
        findings += message_findings("PR title", title, policy)
        findings += content_findings("PR body", pr.get("body") or "")
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
        exempt_paths = any(fnmatchcase(path, pattern) for pattern in path_exceptions)
        findings += content_findings(path, path, path=True, exempt_paths=exempt_paths)
        if git(root, "--literal-pathspecs", "ls-tree", head, "--", path).startswith("160000 "):
            continue
        blob = git(root, "cat-file", "blob", head + ":" + path, binary=True)
        if b"\0" in blob[:8000]:
            continue
        patch = git(root, "--literal-pathspecs", "diff", "--text", "--no-ext-diff", "--no-textconv", "--no-color",
                    "--no-renames", "--unified=0", comparison, head, "--", path)
        findings += added_findings(patch, path, exempt_paths=exempt_paths)
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--declaration-root", type=Path, required=True)
    parser.add_argument("--declaration-revision", required=True)
    parser.add_argument("--event", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME"))
    parser.add_argument("--path-exceptions", default="", help="Newline-separated repository-relative globs for path exceptions")
    parser.add_argument("--fixture", type=Path, help="Use offline GET responses and a fixture declaration")
    args = parser.parse_args(argv)
    try:
        path_exceptions = parse_path_exceptions(args.path_exceptions)
        text = declaration.revision(args.declaration_root, args.declaration_revision, offline=bool(args.fixture))
        policy = declaration.source_policy(text)
        if not args.event:
            raise ValueError("event file is required")
        api = Fixture(args.fixture) if args.fixture else GitHub()
        findings = check(args.root, json.loads(Path(args.event).read_text()), args.event_name, policy, api,
                         path_exceptions=path_exceptions)
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
