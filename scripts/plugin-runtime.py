#!/usr/bin/env python3
"""Deliver and verify the shared Computer MCP Python plugin runtime.

    python3 scripts/plugin-runtime.py sync <checkout>
    python3 scripts/plugin-runtime.py check <checkout>
    python3 scripts/plugin-runtime.py check-workflow
"""

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "plugin-runtime/plugin_runtime.py"
WORKFLOW = ROOT / ".github/workflows/plugin-runtime.yml"
TARGET = "bin/plugin_runtime.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_path(checkout):
    root = Path(checkout).resolve()
    if not root.is_dir():
        raise ValueError(f"Checkout is not a directory: {checkout}")
    path = (root / TARGET).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Runtime path escapes the checkout: {TARGET}")
    return path


def check(checkout):
    path = runtime_path(checkout)
    if not path.is_file():
        raise ValueError(f"Missing plugin runtime: {TARGET}")
    if digest(path) != digest(CANONICAL):
        raise ValueError(f"Plugin runtime differs from the canonical file: {TARGET}")
    print("Plugin runtime matches the canonical file", flush=True)
    return 0


def sync(checkout):
    path = runtime_path(checkout)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CANONICAL, path)
    return check(checkout)


def check_workflow():
    values = re.findall(r"^ +PLUGIN_RUNTIME_SHA256: (.+)$", WORKFLOW.read_text(), re.MULTILINE)
    if len(values) != 1 or not re.fullmatch(r"'[0-9a-f]{64}'", values[0]):
        raise ValueError("Workflow must embed exactly one quoted PLUGIN_RUNTIME_SHA256 digest")
    if values[0][1:-1] != digest(CANONICAL):
        raise ValueError("Workflow PLUGIN_RUNTIME_SHA256 differs from the canonical runtime")
    print("Workflow digest matches the canonical runtime", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("sync", "check"):
        commands.add_parser(command).add_argument("checkout")
    commands.add_parser("check-workflow")
    args = parser.parse_args()
    try:
        if args.command == "check-workflow":
            return check_workflow()
        return sync(args.checkout) if args.command == "sync" else check(args.checkout)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
