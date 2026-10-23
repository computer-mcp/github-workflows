# Computer MCP shared workflows

Reusable GitHub Actions, plugin automation and organization checks for Computer MCP.
The organization's [MAINTENANCE](https://github.com/computer-mcp/.github/blob/master/MAINTENANCE.md)
owns the rules; this repository implements them. Organization and source checks
read the caller's full `.github` commit SHA and report that revision. Missing or
unsupported declarations fail explicitly.

## Workflows and actions

| Entry point | Inputs | Outputs and permissions |
| --- | --- | --- |
| [plugin-runtime.yml](.github/workflows/plugin-runtime.yml) | None | Pass/fail for `bin/plugin_runtime.py`; `contents: read` |
| [plugin-release.yml](.github/workflows/plugin-release.yml) | Required `ref`, `build`, `ci_artifact`; `publish=false`, `runner=ubuntu-24.04` | `published`, `release_id`, `tag`; caller grants `contents: write`, `actions: read`; no secret inputs |
| [actions/notify-catalog](actions/notify-catalog/action.yml) | Required `client-id`, `private-key` | `run-url`; receiver-scoped App token with `actions: write` |
| [organization.yml](.github/workflows/organization.yml) | Required `declaration-revision`; `mode=online` or `offline`; optional secret `organization-token` | `declaration-revision`; GET-only observations; `contents: read` |
| [policy.yml](.github/workflows/policy.yml) | Required `declaration-revision` | `declaration-revision`; pass/fail; `contents: read` |
| [result.yml](.github/workflows/result.yml) | Required `needs-json`; `optional-jobs='[]'` | Pass/fail aggregate; `contents: read` |

[Runtime adoption](PluginRuntime/README.md) describes the unchanged digest
contract. The [release guide](Documentation/Reference/PluginRelease.md) covers
reproducible archives, isolated builds, immutable publication and recovery.
Notification requests the website's existing `pages.yml` on `master`, with no
catalog metadata. `run-url` proves request acceptance; inspect that run for
catalog validation and deployment.

Executable automation lives in lowercase `scripts/`; imported Python modules use
snake_case. `tests/` and `fixtures/` hold offline evidence. Operating and adoption
guides live in `Documentation/Reference/`.

## Pins and versions

This repository versions independently under the organization's
[VERSIONING](https://github.com/computer-mcp/.github/blob/master/VERSIONING.md).
Consumers pin a reviewed full 40-hex commit SHA. Released pins carry a `# vX.Y.Z`
comment; in-progress pins carry no version comment. A tag is not needed to test
an in-progress commit. Update interfaces and copied runtime bytes through
consumer pull requests after a representative consumer run.

Every reusable job executing shared scripts checks out its own repository at
`job.workflow_sha`. These [GitHub workflow identity fields](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#job-context)
refer to the reusable workflow rather than the caller. The release build job
executes the caller's build on its own runner, without shared publisher code.

Replace `<workflow-sha>` and `<declaration-sha>` below with full 40-hex SHAs:

```yaml
jobs:
  runtime:
    uses: computer-mcp/github-workflows/.github/workflows/plugin-runtime.yml@<workflow-sha>
```

A release caller grants the permission ceiling for the isolated jobs:

```yaml
jobs:
  release:
    permissions:
      contents: write
      actions: read
    uses: computer-mcp/github-workflows/.github/workflows/plugin-release.yml@<workflow-sha>
    with:
      ref: ${{ inputs.ref }}
      publish: ${{ inputs.publish }}
      build: python3 scripts/build-package.py
      ci_artifact: widget-${commit}
```

The release guide supplies the complete dispatch trigger. Release callers must
preserve running and queued publications and use no caches. Notification remains
a dependent job or step after successful publication:

```yaml
- name: Request catalog reconciliation
  id: catalog
  uses: computer-mcp/github-workflows/actions/notify-catalog@<workflow-sha>
  with:
    client-id: ${{ vars.CATALOG_APP_CLIENT_ID }}
    private-key: ${{ secrets.CATALOG_APP_PRIVATE_KEY }}
```

## Organization check

The catalog uses `organization.login` and `groups[].repositories[]`. This checker
validates the membership and `name`/`about` fields it consumes; the profile
renderer owns the complete visual schema. Membership must equal the public,
non-archived, non-fork inventory except `.github`. Every member needs a nonempty
GitHub About exactly matching its catalog `about`.

Settings come from MAINTENANCE's default branch, branch requirements, GitHub
settings prose and App table. Checks cover squash-only merging, branch cleanup,
workflow token permissions, default-branch protection, required checks, merge
queues, installed Apps, permission/event/repository scopes and allowed
secret/variable **names**. Fork branch names remain upstream-owned. All API
operations are GET requests; secret values are never read.

```yaml
jobs:
  organization:
    uses: computer-mcp/github-workflows/.github/workflows/organization.yml@<workflow-sha>
    with:
      declaration-revision: <declaration-sha>
```

Online mode reads both documents at that revision and reports a missing
`profile/catalog.json` before calling GitHub. Exit `0` means all observations
match, `1` means drift/invalid input, and `2` means observations are unavailable.
Administrative read access is needed for settings and App installation repository
lists. A normal workflow token may produce unavailable observations. The optional
`organization-token` secret accepts an already authorized credential; it does
not provision credentials or authorize an additional stored secret.

Offline mode uses only the bundled declaration and GET-response fixture, labels
its revision as fixture evidence and makes no live conformance claim.

## Source policy

The implementation maps to [MAINTENANCE: Branches and changes](https://github.com/computer-mcp/.github/blob/master/MAINTENANCE.md#branches-and-changes)
and [Signing](https://github.com/computer-mcp/.github/blob/master/MAINTENANCE.md#signing):

| Declared rule | Enforcement |
| --- | --- |
| Owner identity and SSH signing; GitHub-created commits signed by GitHub | On default-branch pushes, every added commit must be GitHub-verified with reason `valid`, and use the declared owner identity plus an SSH signature or GitHub's `web-flow` committer identity |
| Dependabot may author changes | Original authors are unrestricted; accepted committer/signature checks still apply |
| Conventional Commit types, optional scope and breaking marker | PR titles and added commit subjects use the types parsed from the declaration |
| No tool/agent attribution; human co-authors allowed | Attribution statements and identifiable tool/bot co-author trailers are rejected in titles, commit messages and added text; human co-authors and ordinary product references are retained |
| No maintainer-machine paths or local task-state references | Added/modified paths, added text and messages are checked for concrete home-directory paths and local task-file references |
| PR titles, added content and added/modified paths; verified default-branch commits | PR diffs use the merge base; pushes check their supplied range; removed lines are outside the added-content check |

`merge_group` checks queued content and paths. Temporary queue commits are not
accepted default-branch commits; final push checks verify the accepted commits.
The checker reads Git blobs and forces text diffs for text files so consumer
attributes cannot suppress scanning. Binary payloads are not decoded; their
paths are checked. Attribution recognition is textual, not proof of the identity
of every named co-author.

Keep policy separate from build/test CI. Title edits rerun policy without
replacing an existing validation result:

```yaml
name: Source policy checks
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
  push:
    branches: [master]
  merge_group:
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
jobs:
  policy:
    uses: computer-mcp/github-workflows/.github/workflows/policy.yml@<workflow-sha>
    with:
      declaration-revision: <declaration-sha>
```

This repository's [policy caller](.github/workflows/source-policy.yml) resolves
organization default-branch rules to one SHA per run and calls the same policy.
Until those rules reach the organization's default branch, this check correctly
fails for missing declarations. No temporary organization revision is embedded.

## Aggregation

Use `always()` on the caller and reusable aggregate. Required dependencies must
succeed. Jobs named in `optional-jobs` may be skipped; failure and cancellation
always fail. Missing and malformed results fail too.

```yaml
jobs:
  validate:
    if: always()
    needs: [package, runtime]
    uses: computer-mcp/github-workflows/.github/workflows/result.yml@<workflow-sha>
    with:
      needs-json: ${{ toJSON(needs) }}
```

Observe actual caller/callee check names before selecting required checks. This
repository does not configure rulesets.

## Local verification

Python 3.13+ runs runtime and release fixtures. Checkers use the standard library;
YAML validation uses pinned PyYAML.

```sh
python3 -m venv .build/venv
.build/venv/bin/python -m pip install --no-cache-dir -r requirements-test.txt
.build/venv/bin/python -m unittest discover -s tests
.build/venv/bin/python scripts/check-workflows.py
python3 scripts/plugin-runtime.py check-workflow
python3 scripts/check-organization.py --mode offline \
  --declaration-root fixtures/declaration \
  --declaration-revision 1111111111111111111111111111111111111111 \
  --fixture fixtures/organization.json
```

The offline revision is a fixture label. For online checks, check out the selected
`.github` commit, pass its directory and actual SHA, select `--mode online` and
omit `--fixture`. Online reads use Git objects at that SHA, not uncommitted edits.

The workflow validator always checks YAML, duplicate keys, action pins and
workflow boundaries. If actionlint is available it also runs that tool, filtering
only the older-linter error for documented `job.workflow_*` fields. All other
errors remain fatal. Tests cover runtime delivery, release assembly/recovery,
publication fault injection, notifier transport, organization drift, source
ranges and aggregation offline. Temporary environments belong in ignored
`.build/` and may be removed after checking.

The [adoption checklist](Documentation/Reference/Adoption.md) names consumer files
and rollout prerequisites.
