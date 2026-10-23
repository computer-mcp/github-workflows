import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workflows", ROOT / "scripts/check-workflows.py")
workflows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflows)


class WorkflowTests(unittest.TestCase):
    def test_actual_workflows_and_action_pass_contracts(self):
        self.assertEqual(len(workflows.validate()), 8)

    def test_duplicate_yaml_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "workflow.yml"
            file.write_text("jobs:\n  test: {}\n  test: {}\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                workflows.read(file)

    def test_unpinned_actions_are_rejected(self):
        for use in ("actions/checkout@main", "actions/checkout@v7", "actions/checkout@abcd"):
            with self.assertRaisesRegex(ValueError, "full SHA"):
                workflows.check_uses({"uses": use})

    def test_notify_action_retains_receiver_permissions_and_output(self):
        action = workflows.read(ROOT / "actions/notify-catalog/action.yml")
        token = action["runs"]["steps"][0]["with"]
        self.assertEqual(token["owner"], "computer-mcp")
        self.assertEqual(token["repositories"], "computer-mcp.github.io")
        self.assertEqual(token["permission-actions"], "write")
        self.assertEqual(set(action["inputs"]), {"client-id", "private-key"})
        self.assertEqual(set(action["outputs"]), {"run-url"})

    def test_policy_path_exceptions_are_optional_and_passed_as_data(self):
        workflow = workflows.read(ROOT / ".github/workflows/policy.yml")
        argument = workflow["on"]["workflow_call"]["inputs"]["path-exceptions"]
        self.assertEqual(argument["type"], "string")
        self.assertEqual(argument["default"], "")
        step = workflow["jobs"]["policy"]["steps"][-1]
        self.assertEqual(step["env"]["PATH_EXCEPTIONS"], "${{ inputs.path-exceptions }}")
        self.assertIn('--path-exceptions "$PATH_EXCEPTIONS"', step["run"])
        self.assertNotIn("${{ inputs.path-exceptions }}", step["run"])

    def test_release_and_runtime_keep_public_interfaces(self):
        release = workflows.read(ROOT / ".github/workflows/plugin-release.yml")["on"]["workflow_call"]
        self.assertEqual(set(release["inputs"]), {"ref", "publish", "build", "ci_artifact", "runner"})
        self.assertEqual(set(release["outputs"]), {"published", "release_id", "tag"})
        runtime = workflows.read(ROOT / ".github/workflows/plugin-runtime.yml")["on"]
        self.assertEqual(runtime["workflow_call"], "")

    def test_terminal_demo_interface_and_permissions(self):
        workflow = workflows.read(ROOT / ".github/workflows/terminal-demo.yml")
        call = workflow["on"]["workflow_call"]
        self.assertEqual(set(call["inputs"]), {"artifact", "archive", "executable", "assets", "runner"})
        self.assertNotIn("outputs", call)
        for name in ("artifact", "executable", "runner"):
            self.assertEqual(call["inputs"][name]["required"], "true")
            self.assertEqual(call["inputs"][name]["type"], "string")
        self.assertEqual(call["inputs"]["archive"]["default"], "")
        self.assertEqual(call["inputs"]["assets"]["default"], ".github/assets/terminal")
        self.assertEqual(set(workflow["jobs"]), {"demo"})
        job = workflow["jobs"]["demo"]
        self.assertEqual(workflow["permissions"], {})
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertEqual(job["runs-on"], "${{ inputs.runner }}")
        self.assertGreater(int(job["timeout-minutes"]), 0)
        self.assertNotIn("outputs", job)
        self.assertNotIn("concurrency", workflow)
        self.assertNotIn("concurrency", job)
        self.assertNotIn("cache", (ROOT / ".github/workflows/terminal-demo.yml").read_text().lower())

    def test_terminal_demo_uses_caller_source_and_pinned_recording_check(self):
        steps = workflows.read(ROOT / ".github/workflows/terminal-demo.yml")["jobs"]["demo"]["steps"]
        self.assertEqual(steps[0]["with"]["ref"], "${{ github.sha }}")
        for step in steps:
            if step.get("uses", "").startswith("actions/checkout@"):
                self.assertEqual(step["with"]["persist-credentials"], "false")
            if "run" in step:
                self.assertEqual(step["shell"], "bash")
                self.assertIn("set -euo pipefail", step["run"])
                self.assertNotIn("${{", step["run"])
        directory = next(step for step in steps if step.get("id") == "directory")
        self.assertIn('mktemp -d "$RUNNER_TEMP/', directory["run"])
        download = next(step for step in steps if step.get("uses", "").startswith("actions/download-artifact@"))
        self.assertEqual(download["with"], {"name": "${{ inputs.artifact }}",
                                            "path": "${{ steps.directory.outputs.path }}/artifact"})
        executable = next(step for step in steps if step.get("id") == "executable")
        self.assertEqual(executable["env"]["DEMO_ARCHIVE"], "${{ inputs.archive }}")
        self.assertEqual(executable["env"]["DEMO_EXECUTABLE"], "${{ inputs.executable }}")
        self.assertIn('--archive "$DEMO_ARCHIVE"', executable["run"])
        self.assertIn('--executable "$DEMO_EXECUTABLE"', executable["run"])
        presentation = next(step for step in steps if step.get("uses", "").startswith("showxu/skills/"))
        self.assertEqual(presentation["uses"],
                         "showxu/skills/skills/github-readme-design/scripts@36707036061a2d0ba012184ef0b6d6820082127f")
        self.assertEqual(presentation["with"], {"asset": "terminal", "command": "check",
                                              "recording-only": "true", "assets": "${{ inputs.assets }}",
                                              "executable": "${{ steps.executable.outputs.path }}"})
        self.assertEqual(steps[-1]["if"], "always()")


if __name__ == "__main__":
    unittest.main()
