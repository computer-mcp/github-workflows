#!/usr/bin/env python3
"""Require every dependency to succeed, except explicitly optional skipped jobs."""

import argparse
import json
import os
import sys


def failures(needs, optional):
    if not isinstance(needs, dict) or not needs:
        raise ValueError("needs must be a nonempty object")
    if not isinstance(optional, list) or any(not isinstance(name, str) for name in optional):
        raise ValueError("optional jobs must be a JSON array of names")
    if not set(optional) <= needs.keys():
        raise ValueError("optional jobs must exist in needs")
    failed = []
    for name, job in needs.items():
        result = job.get("result") if isinstance(job, dict) else None
        if result not in {"success", "failure", "cancelled", "skipped"}:
            raise ValueError(f"{name}: missing or invalid result")
        if result != "success" and not (result == "skipped" and name in optional):
            failed.append(name)
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--needs", default=os.environ.get("NEEDS"))
    parser.add_argument("--optional", default=os.environ.get("OPTIONAL_JOBS", "[]"))
    args = parser.parse_args()
    try:
        failed = failures(json.loads(args.needs or "null"), json.loads(args.optional))
        if failed:
            raise ValueError("jobs did not succeed: " + ", ".join(failed))
        print("PASS all required jobs succeeded")
        return 0
    except ValueError as error:
        print("FAIL " + str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
