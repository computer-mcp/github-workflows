#!/usr/bin/env python3
"""Resolve a built CLI within an artifact or a safely extracted .tar.gz."""

import argparse
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tarfile
import tempfile


def require_relative(value, label):
    paths = (PurePosixPath(value), PureWindowsPath(value))
    if (not value or any(character in value for character in "\0\r\n") or
            any(path.is_absolute() or path.drive or ".." in path.parts for path in paths)):
        raise ValueError(f"{label} must be a relative path without '..' or line breaks")


def match_file(root, pattern, label):
    require_relative(pattern, label)
    matches = list(root.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"{label} must match exactly one file; found {len(matches)}")
    target = matches[0].resolve(strict=True)
    if not target.is_relative_to(root):
        raise ValueError(f"{label} resolves outside its directory")
    if not target.is_file():
        raise ValueError(f"{label} must be a regular file")
    if any(character in str(target) for character in "\r\n"):
        raise ValueError(f"{label} path must not contain line breaks")
    return target


def archive_member(member, destination):
    require_relative(member.name, "archive member")
    return tarfile.data_filter(member, destination)


def resolve(artifact_dir, archive, executable):
    root = Path(artifact_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("artifact directory must be a directory")
    require_relative(executable, "executable")
    if archive:
        bundle = match_file(root, archive, "archive")
        if not bundle.name.endswith(".tar.gz"):
            raise ValueError("archive must be a .tar.gz file")
        root = Path(tempfile.mkdtemp(prefix="terminal-demo-extracted-", dir=root.parent))
        with tarfile.open(bundle, "r:gz") as source:
            source.extractall(root, filter=archive_member)
    target = match_file(root, executable, "executable")
    if not os.access(target, os.X_OK):
        raise ValueError("executable must have executable permission")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--archive", default="")
    parser.add_argument("--executable", required=True)
    args = parser.parse_args(argv)
    try:
        print(resolve(args.artifact_dir, args.archive, args.executable))
        return 0
    except (OSError, ValueError, tarfile.TarError) as error:
        print("FAIL terminal demo: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
