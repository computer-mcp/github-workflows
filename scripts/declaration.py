"""Read the supported MAINTENANCE prose; absent declarations never become defaults."""

from pathlib import Path
import re
import subprocess


def section(text, heading):
    match = re.search(r"^## " + re.escape(heading) + r"\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise ValueError(f"MAINTENANCE.md: missing {heading} section")
    return " ".join(match[1].split())


def require(text, phrases, label):
    for phrase in phrases:
        if phrase not in text:
            raise ValueError(f"MAINTENANCE.md: unsupported or missing {label} declaration: {phrase}")


def source_policy(text):
    changes = section(text, "Branches and changes")
    signing = section(text, "Signing")
    require(changes, ["are SSH-signed", "are signed by GitHub", "Dependabot may author changes.",
                     "Pull request titles and commit subjects follow Conventional Commits:",
                     "optional scope and `!`", "Commits and pull requests carry no tool or agent attribution",
                     "real human co-authors may be credited.",
                     "Committed content contains no paths from a maintainer's machine",
                     "no references into local `.agent/` task state.",
                     "checks pull request titles, added content and added or modified paths",
                     "requires default-branch commits to be verified and committed by GitHub or the owner."],
            "source policy")
    require(signing, ["gpg.format ssh", "commit.gpgsign true", "registered as a signing key on GitHub"], "signing")
    identity = re.search(r"owner's name `([^`]+)` and noreply email `([^`]+)`", changes)
    types = re.search(r"Types are (.*?)\.", changes)
    branch = re.search(r"The default branch is `([^`]+)`", changes)
    if not identity or not types or not branch:
        raise ValueError("MAINTENANCE.md: missing identity, commit types or default branch")
    names = re.findall(r"`([a-z]+)`", types[1])
    if not names or len(names) != len(set(names)):
        raise ValueError("MAINTENANCE.md: invalid Conventional Commit types")
    return {"owner": identity[1], "email": identity[2], "types": names, "default_branch": branch[1]}


def settings_policy(text):
    changes = section(text, "Branches and changes")
    settings = section(text, "GitHub settings")
    require(changes, ["A fork keeps its upstream branch names", "ruleset that has no bypass", "blocks deletion and force pushes",
                     "requires signed commits", "only squash-merged pull requests",
                     "only after its own required checks pass"], "branch rules")
    require(settings, ["Every repository allows only squash merges and deletes merged branches.",
                       "read-only token that cannot approve pull requests.",
                       "Each public repository's `default branch` ruleset requires at least one check",
                       "the only ruleset with a merge queue", "do not also require an up-to-date branch.",
                       "Only these GitHub Apps are installed.", "exactly the listed permissions",
                       "installed only on the listed repositories", "subscribes to no events",
                       "No repository and not the organization holds any other Actions secret or variable."], "settings")
    branch = re.search(r"The default branch is `([^`]+)`", changes)
    queue = re.search(r"The `([^`]+)` default branch ruleset is the only ruleset with a merge queue", settings)
    credential_names = re.search(r"client ID in the `(<credentials>[^`]+)` variable and its private key in the "
                                 r"`(<credentials>[^`]+)` secret", settings)
    if not branch or not queue:
        raise ValueError("MAINTENANCE.md: missing default branch or merge queue owner")
    if not credential_names:
        raise ValueError("MAINTENANCE.md: missing App credential naming declaration")
    raw = text.split("## GitHub settings\n", 1)[1].split("\n## ", 1)[0]
    rows = [line.strip().strip("|").split("|") for line in raw.splitlines() if line.startswith("|")]
    columns = ["App", "Permissions", "Installed on", "Credentials", "Stored in"]
    if len(rows) < 3 or [cell.strip() for cell in rows[0]] != columns:
        raise ValueError("MAINTENANCE.md: missing GitHub Apps table")
    apps = {}
    for row in rows[2:]:
        try:
            (slug,), permissions, installed, (prefix,), stored = [re.findall(r"`([^`]+)`", cell) for cell in row]
            permissions = dict(permission.split(": ") for permission in permissions)
        except ValueError:
            raise ValueError("MAINTENANCE.md: malformed GitHub Apps row") from None
        if slug in apps or not installed or not stored or not permissions:
            raise ValueError("MAINTENANCE.md: duplicate or incomplete GitHub App")
        apps[slug] = {"permissions": permissions, "installed": sorted(installed), "prefix": prefix, "stored": stored}
    return {"default_branch": branch[1], "queue_repository": queue[1], "apps": apps,
            "credential_variable": credential_names[1], "credential_secret": credential_names[2]}


def revision(root, expected, *, offline=False):
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("declaration-revision must be a full 40-hex commit SHA")
    if not offline:
        actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        if actual != expected:
            raise ValueError("declaration checkout does not match declaration-revision")
    print(f"MAINTENANCE revision: {expected}" + (" (offline fixture)" if offline else ""))
    return read_file(root, "MAINTENANCE.md", None if offline else expected)


def read_file(root, path, revision=None):
    if revision is None:
        return (Path(root) / path).read_text(encoding="utf-8")
    try:
        return subprocess.check_output(["git", "-C", str(root), "show", revision + ":" + path],
                                       stderr=subprocess.DEVNULL).decode("utf-8")
    except subprocess.CalledProcessError:
        raise ValueError(f"{path} is missing at the requested .github revision") from None
