# Shared Python plugin runtime

[plugin_runtime.py](../plugin-runtime/plugin_runtime.py) is the canonical stdlib runtime shared by
the Claude, Cursor and TRAE plugins. It provides stdio MCP, bounded JSON and
schema validation, process ownership and cleanup, cancellation, event buffers
and native-version checks. Each plugin owns its vendor adapter, version
baseline and supported Python versions.

## Adoption and updates

From the organization shared-workflows checkout at the revision the plugin will pin:

```sh
python3 scripts/plugin-runtime.py sync <plugin-checkout>
python3 scripts/plugin-runtime.py check <plugin-checkout>
```

`sync` copies the canonical file to `bin/plugin_runtime.py` and checks it;
`check` is read-only and fails if that file is missing or differs byte for byte.
Both commands require an existing checkout directory and keep delivery paths
inside it.

Adapters whose native assertion lives in `cli-tree.json` import
`expected_version` and pass its result to `verify_version`:

```python
from plugin_runtime import expected_version, verify_version

verify_version(executable, expected_version(TREE), job, cwd, retain_process)
```

`expected_version(tree)` returns the `stdout` of its `--version` executable
check. A missing assertion raises `Failure('invalid_configuration', 'Package
lacks its native version assertion')` before any process starts. Claude and
Cursor use this form. TRAE keeps its direct version-string call:

```python
verify_version(executable, NATIVE_VERSION, job, cwd, retain_process)
```

`verify_version(executable, expected, job, cwd, retain_process=None)` runs the
owned native `--version` process, compares its exact output with `expected`,
and preserves the runtime's deadlines, output bound, cancellation and cleanup.
The optional callback retains the version process for adapter shutdown.

Add a job to the plugin's CI, pinning the reusable workflow by the full
40-character commit SHA of this repository revision that supplied the file:

```yaml
jobs:
  runtime:
    uses: computer-mcp/github-workflows/.github/workflows/plugin-runtime.yml@<full-commit-sha>
```

The workflow has no inputs or secrets. With read-only `contents` permission,
it checks out the caller without persisting credentials and compares
`bin/plugin_runtime.py` with the SHA-256 embedded in that pinned workflow.
The copied runtime and workflow pin are updated together in the consumer's
pull request, with its own adapter tests passing.

## Maintaining the canonical runtime

After changing the canonical file, update `PLUGIN_RUNTIME_SHA256` in
`.github/workflows/plugin-runtime.yml` to its SHA-256. Check the tools and
embedded digest after the root README's environment setup:

```sh
.build/venv/bin/python -m unittest discover -s tests
python3 scripts/plugin-runtime.py check-workflow
```

The organization CI runs both commands. Consumer behavior is verified with the
plugins' own suites; those repositories own their test entry points.
