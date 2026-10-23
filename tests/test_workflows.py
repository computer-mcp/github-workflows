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
        self.assertEqual(len(workflows.validate()), 7)

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


if __name__ == "__main__":
    unittest.main()
