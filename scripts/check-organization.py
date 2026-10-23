#!/usr/bin/env python3
"""Check catalog membership, About text and declared settings using GET only."""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import declaration
from github_api import Fixture, GitHub, Unavailable, unique_object
import settings


def read_catalog(root, organization, revision=None):
    path = Path(root) / "profile/catalog.json"
    if revision is None and not path.is_file():
        raise ValueError("profile/catalog.json is missing at the requested .github revision")
    catalog = json.loads(declaration.read_file(root, "profile/catalog.json", revision), object_pairs_hook=unique_object)
    # The profile renderer owns the complete visual schema in catalog.ts.
    # This projection validates every field used for membership and About checks.
    try:
        if catalog["organization"]["login"] != organization or not isinstance(catalog["groups"], list):
            raise ValueError("catalog organization/groups do not match the requested organization")
        entries = {}
        for group in catalog["groups"]:
            if not isinstance(group["repositories"], list) or not group["repositories"]:
                raise ValueError("catalog group repositories must be a nonempty array")
            for entry in group["repositories"]:
                name, about = entry["name"], entry["about"]
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", "..", ".github", ".github-private"}:
                    raise ValueError("invalid public catalog repository name")
                if name.lower() in entries:
                    raise ValueError("duplicate catalog repository: " + name)
                if not isinstance(about, str) or not about.strip():
                    raise ValueError(f"{name}: catalog about must be nonempty")
                entries[name.lower()] = entry
    except (KeyError, TypeError):
        raise ValueError("catalog requires organization.login and groups[].repositories[].name/about") from None
    return entries


def membership(entries, repositories):
    if not isinstance(repositories, list) or any(not isinstance(repo, dict) or not isinstance(repo.get("name"), str)
            or any(type(repo.get(key)) is not bool for key in ("private", "archived", "fork")) for repo in repositories):
        raise ValueError("GitHub returned an invalid repository inventory")
    live = {repo["name"].lower(): repo for repo in repositories
            if not repo["private"] and not repo["archived"] and not repo["fork"] and repo["name"] != ".github"}
    findings = [f"DRIFT catalog: missing {name}" for name in sorted(live.keys() - entries.keys())]
    findings += [f"DRIFT catalog: extra {name}" for name in sorted(entries.keys() - live.keys())]
    for name in sorted(live):
        about = live[name].get("description")
        if not isinstance(about, str) or not about.strip():
            findings.append(f"DRIFT {name}: GitHub About is empty or unavailable")
        elif name in entries and about != entries[name]["about"]:
            findings.append(f"DRIFT {name}: catalog about {entries[name]['about']!r}; GitHub About {about!r}")
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declaration-root", type=Path, required=True)
    parser.add_argument("--declaration-revision", required=True)
    parser.add_argument("--organization", default="computer-mcp")
    parser.add_argument("--mode", choices=("offline", "online"), default="online")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--scope", choices=("membership", "full"), default="full",
                        help="membership checks inventory and About; full adds declared settings")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", args.organization):
            raise ValueError("invalid organization")
        if (args.mode == "offline") != bool(args.fixture):
            raise ValueError("offline mode requires --fixture; online mode does not accept fixtures")
        text = declaration.revision(args.declaration_root, args.declaration_revision, offline=args.mode == "offline")
        entries = read_catalog(args.declaration_root, args.organization, None if args.mode == "offline" else args.declaration_revision)
        expected = declaration.settings_policy(text)
        api = Fixture(args.fixture) if args.fixture else GitHub()
        repositories = api.collection(f"orgs/{args.organization}/repos?type=all")
        findings = membership(entries, repositories)
        if args.scope == "full":
            findings += settings.check(api, args.organization, expected, repositories)
        for finding in findings:
            print(" ".join(finding.splitlines()))
        if not findings:
            print("PASS organization membership and About" + (" and declared settings" if args.scope == "full" else ""))
        return 2 if any(f.startswith("UNKNOWN ") for f in findings) else int(bool(findings))
    except Unavailable as error:
        print("UNKNOWN organization: " + str(error))
        return 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("FAIL organization: " + " ".join(str(error).splitlines()))
        return 1


if __name__ == "__main__":
    sys.exit(main())
