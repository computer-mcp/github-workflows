import copy
import importlib.util
import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import declaration
from github_api import Fixture, GitHub, Unavailable
import settings

spec = importlib.util.spec_from_file_location("organization", ROOT / "scripts/check-organization.py")
organization = importlib.util.module_from_spec(spec)
spec.loader.exec_module(organization)
STANDARD = ROOT / "fixtures/declaration"
FIXTURE = ROOT / "fixtures/organization.json"
REVISION = "1" * 40


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.api = Fixture(FIXTURE)
        self.policy = declaration.settings_policy((STANDARD / "MAINTENANCE.md").read_text())
        self.repos = self.api.collection("orgs/computer-mcp/repos?type=all")
        self.catalog = organization.read_catalog(STANDARD, "computer-mcp")

    def check_settings(self):
        return settings.check(self.api, "computer-mcp", self.policy, self.repos)

    def test_complete_fixture_passes(self):
        self.assertEqual(organization.membership(self.catalog, self.repos), [])
        self.assertEqual(self.check_settings(), [])

    def test_offline_cli_reports_revision_without_network(self):
        with patch.object(GitHub, "get", side_effect=AssertionError("network")), redirect_stdout(io.StringIO()) as output:
            status = organization.main(["--declaration-root", str(STANDARD), "--declaration-revision", REVISION,
                                        "--mode", "offline", "--fixture", str(FIXTURE)])
        self.assertEqual(status, 0)
        self.assertIn(REVISION + " (offline fixture)", output.getvalue())

    def test_membership_scope_skips_settings_reads(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(settings, "check", side_effect=AssertionError("settings read")):
            code = organization.main(["--mode", "offline", "--declaration-root", str(STANDARD),
                                      "--declaration-revision", REVISION, "--fixture", str(FIXTURE),
                                      "--scope", "membership"])
        self.assertEqual(code, 0)
        self.assertIn("PASS organization membership and About", output.getvalue())
        self.assertNotIn("declared settings", output.getvalue())

    def test_membership_accepts_declaration_without_settings_but_full_rejects_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "MAINTENANCE.md").write_text("# Maintenance\n")
            (root / "profile").mkdir()
            (root / "profile/catalog.json").write_bytes((STANDARD / "profile/catalog.json").read_bytes())
            args = ["--mode", "offline", "--declaration-root", directory,
                    "--declaration-revision", REVISION, "--fixture", str(FIXTURE)]
            with redirect_stdout(io.StringIO()), patch.object(declaration, "settings_policy",
                    side_effect=AssertionError("settings parsed")):
                self.assertEqual(organization.main(args + ["--scope", "membership"]), 0)
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(organization.main(args + ["--scope", "full"]), 1)
            self.assertIn("FAIL organization", output.getvalue())

    def test_online_missing_catalog_fails_clearly_before_api(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "MAINTENANCE.md").write_text((STANDARD / "MAINTENANCE.md").read_text())
            with patch.object(declaration.subprocess, "check_output", side_effect=[REVISION + "\n",
                    (STANDARD / "MAINTENANCE.md").read_bytes(), subprocess.CalledProcessError(128, ["git"])]), \
                    patch.object(GitHub, "get", side_effect=AssertionError("network")), redirect_stdout(io.StringIO()) as output:
                status = organization.main(["--declaration-root", directory, "--declaration-revision", REVISION])
        self.assertEqual(status, 1)
        self.assertIn("profile/catalog.json is missing", output.getvalue())

    def test_revision_mismatch_and_non_sha_are_rejected(self):
        for revision in ("master", "abc123", REVISION):
            with patch.object(declaration.subprocess, "check_output", return_value="2" * 40 + "\n"):
                with self.assertRaises(ValueError):
                    declaration.revision(STANDARD, revision)

    def test_public_membership_excludes_archived_private_forks_and_standards(self):
        self.assertEqual(organization.membership(self.catalog, self.repos), [])
        self.repos.append({"name": "new-tool", "private": False, "archived": False, "fork": False, "description": "New"})
        self.assertIn("DRIFT catalog: missing new-tool", organization.membership(self.catalog, self.repos))
        del self.catalog["github-workflows"]
        self.catalog["stale"] = {"name": "stale", "about": "Stale"}
        self.assertIn("DRIFT catalog: extra stale", organization.membership(self.catalog, self.repos))

    def test_about_is_required_and_exact(self):
        for about in (None, "", "  ", "different"):
            with self.subTest(about=about):
                repos = copy.deepcopy(self.repos)
                next(repo for repo in repos if repo["name"] == "github-workflows")["description"] = about
                self.assertTrue(organization.membership(self.catalog, repos))

    def test_duplicate_and_malformed_catalog_fields(self):
        value = json.loads((STANDARD / "profile/catalog.json").read_text())
        cases = []
        duplicate = copy.deepcopy(value)
        duplicate["groups"][0]["repositories"].append({**duplicate["groups"][0]["repositories"][0], "name": "COMPUTER-MCP"})
        cases.append(duplicate)
        for field, invalid in (("name", ".github"), ("name", "../escape"), ("about", " ")):
            item = copy.deepcopy(value)
            item["groups"][0]["repositories"][0][field] = invalid
            cases.append(item)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile").mkdir()
            for value in cases:
                (root / "profile/catalog.json").write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    organization.read_catalog(root, "computer-mcp")
            (root / "profile/catalog.json").write_text('{"groups":[],"groups":[]}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                organization.read_catalog(root, "computer-mcp")

    def test_missing_declarations_fail_instead_of_using_builtins(self):
        original = (STANDARD / "MAINTENANCE.md").read_text()
        for phrase in ("Every repository allows only squash merges", "requires signed commits", "Installed on"):
            with self.assertRaises(ValueError):
                declaration.settings_policy(re.sub(r"\s+".join(map(re.escape, phrase.split())), "changed declaration", original))
        changed = original.replace("The default branch is `master`", "The default branch is `trunk`")
        policy = declaration.settings_policy(changed)
        self.assertEqual(policy["default_branch"], "trunk")

    def test_credential_names_come_from_the_declaration(self):
        text = (STANDARD / "MAINTENANCE.md").read_text()
        self.policy = declaration.settings_policy(text.replace("<credentials>_CLIENT_ID", "<credentials>_IDENTIFIER"))
        self.assertTrue(any("_IDENTIFIER" in f for f in self.check_settings()))
        with self.assertRaisesRegex(ValueError, "credential naming"):
            declaration.settings_policy(text.replace("<credentials>_CLIENT_ID", "missing"))

    def test_online_declaration_reads_committed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            (root / "MAINTENANCE.md").write_text("committed declaration\n")
            subprocess.run(["git", "-C", directory, "add", "MAINTENANCE.md"], check=True)
            subprocess.run(["git", "-C", directory, "-c", "commit.gpgsign=false", "-c", "user.name=Fixture",
                            "-c", "user.email=fixture@example.org", "commit", "-qm", "docs: fixture"], check=True)
            revision = subprocess.check_output(["git", "-C", directory, "rev-parse", "HEAD"], text=True).strip()
            (root / "MAINTENANCE.md").write_text("uncommitted replacement\n")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(declaration.revision(root, revision), "committed declaration\n")

    def test_each_merge_and_token_setting_is_checked(self):
        root = "repos/computer-mcp/github-workflows"
        for key in settings.MERGES:
            with self.subTest(key=key):
                self.api = Fixture(FIXTURE)
                self.api.responses[root][key] = not settings.MERGES[key]
                self.assertTrue(any(key in f for f in self.check_settings()))
        for path in (root, "orgs/computer-mcp"):
            self.api = Fixture(FIXTURE)
            self.api.responses[path + "/actions/permissions/workflow"]["can_approve_pull_request_reviews"] = True
            self.assertTrue(any("can_approve" in f for f in self.check_settings()))

    def test_required_rules_and_targets_are_checked(self):
        path = "repos/computer-mcp/github-workflows/rulesets/1"
        for kind in settings.RULES:
            self.api = Fixture(FIXTURE)
            self.api.responses[path]["rules"] = [r for r in self.api.responses[path]["rules"] if r["type"] != kind]
            self.assertTrue(any("missing " + kind in f for f in self.check_settings()))
        for key, value in (("target", "tag"), ("enforcement", "evaluate"), ("bypass_actors", [{"actor_id": 1}])):
            self.api = Fixture(FIXTURE)
            self.api.responses[path][key] = value
            self.assertTrue(any(key in f for f in self.check_settings()))
        self.api = Fixture(FIXTURE)
        self.api.responses[path]["conditions"]["ref_name"]["exclude"] = ["refs/heads/master"]
        self.assertTrue(any("exclude" in f for f in self.check_settings()))

    def test_queue_requires_squash_allgreen_and_non_strict_checks(self):
        path = "repos/computer-mcp/computer-mcp/rulesets/1"
        for kind, key, value in (("merge_queue", "merge_method", "MERGE"), ("merge_queue", "grouping_strategy", "HEADGREEN"),
                                 ("required_status_checks", "strict_required_status_checks_policy", True)):
            self.api = Fixture(FIXTURE)
            next(r for r in self.api.responses[path]["rules"] if r["type"] == kind)["parameters"][key] = value
            self.assertTrue(any(key in f for f in self.check_settings()))

    def test_inherited_or_other_repository_queue_fails(self):
        root = "repos/computer-mcp/github-workflows"
        self.api.responses[root + "/rulesets/1"]["rules"].append({"type": "merge_queue"})
        self.assertTrue(any("undeclared merge queue" in f for f in self.check_settings()))
        self.api = Fixture(FIXTURE)
        self.api.responses[root + "/rulesets?includes_parents=true&per_page=100&page=1"].append(
            {"id": 2, "name": "shared", "source": "computer-mcp", "source_type": "Organization"})
        self.api.responses["orgs/computer-mcp/rulesets/2"] = {"name": "shared", "rules": [{"type": "merge_queue"}]}
        self.assertTrue(any("undeclared merge queue" in f for f in self.check_settings()))

    def test_apps_permissions_events_selection_and_credentials(self):
        path = "orgs/computer-mcp/installations?per_page=100&page=1"
        for key, value in (("permissions", {"contents": "write"}), ("events", ["push"]), ("repository_selection", "all")):
            self.api = Fixture(FIXTURE)
            self.api.responses[path]["installations"][0][key] = value
            self.assertTrue(any(key in f for f in self.check_settings()))
        self.api = Fixture(FIXTURE)
        self.api.responses["user/installations/1/repositories?per_page=100&page=1"]["repositories"] = []
        self.assertTrue(any("repositories" in f for f in self.check_settings()))
        self.api = Fixture(FIXTURE)
        self.api.responses["orgs/computer-mcp/actions/secrets?per_page=100&page=1"]["secrets"] = [{"name": "EXTRA"}]
        self.assertTrue(any("EXTRA" in f for f in self.check_settings()))

    def test_unavailable_observation_is_unknown_and_nonzero(self):
        del self.api.responses["user/installations/1/repositories?per_page=100&page=1"]
        self.assertTrue(any(f.startswith("UNKNOWN ") for f in self.check_settings()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api.json"
            path.write_text(json.dumps(self.api.responses))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(organization.main(["--declaration-root", str(STANDARD), "--declaration-revision", REVISION,
                                                   "--mode", "offline", "--fixture", str(path)]), 2)

    def test_collections_paginate_objects_and_lists(self):
        for key in (None, "installations", "repositories", "secrets", "variables"):
            with patch.object(GitHub, "get", side_effect=[{key: [1] * 100} if key else [1] * 100,
                                                        {key: [2]} if key else [2]]) as get:
                self.assertEqual(len(GitHub().collection("orgs/example/items", key)), 101)
                self.assertIn("page=2", get.call_args.args[0])

    def test_transport_is_get_only_and_redacts_failures(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "credential")) as run:
            with self.assertRaises(Unavailable) as error:
                GitHub().get("orgs/computer-mcp/installations")
        self.assertNotIn("credential", str(error.exception))
        self.assertEqual(run.call_args.args[0][2:4], ["--method", "GET"])


if __name__ == "__main__":
    unittest.main()
