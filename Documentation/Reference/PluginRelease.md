# Plugin release workflow

The reusable [workflow](../../.github/workflows/plugin-release.yml) builds and
publishes reproducible plugin packages. [Shared VERSIONING](https://github.com/computer-mcp/.github/blob/master/VERSIONING.md#plugin-release-contents)
owns the contents, receipt schema, provenance and recovery rules. Codex uses its
documented native artifact promotion exception.

## Caller

Add `.github/workflows/release.yml` in the plugin repository, substituting the
full shared-workflows commit SHA and the exact artifact name from its `ci.yml`:

```yaml
name: Release
on:
  workflow_dispatch:
    inputs:
      ref:
        description: Version tag, or commit for a dry run
        type: string
        required: true
      publish:
        description: Publish the verified release
        type: boolean
        default: false
permissions: {}
jobs:
  release:
    permissions:
      contents: write
      actions: read
    uses: computer-mcp/github-workflows/.github/workflows/plugin-release.yml@<full-commit-sha>
    with:
      ref: ${{ inputs.ref }}
      publish: ${{ inputs.publish }}
      build: python3 scripts/build-package.py
      ci_artifact: <exact-ci-artifact-name-with-${commit}>
  notify-catalog:
    needs: release
    if: needs.release.outputs.published == 'true'
    permissions: {}
    uses: ./.github/workflows/notify-catalog.yml
    secrets:
      CATALOG_APP_PRIVATE_KEY: ${{ secrets.CATALOG_APP_PRIVATE_KEY }}
```

`notify-catalog.yml` is the caller repository's existing reusable notification
workflow. It receives the catalog App private key; the release workflow has no
secret inputs. The caller grants the permission ceiling needed by these jobs:

| Job | Permissions | Data flow |
| --- | --- | --- |
| `source` | `contents: read`, `actions: read` | Check out the pinned helper and resolve the source commit |
| `build` | `{}` | Check out that commit, execute the caller's build and upload its archives |
| `verify` | `contents: read`, `actions: read` | On a fresh runner, check the helper pin, read the source manifest and both artifacts as data, compare archive bytes and assemble the bundle |
| `publish` | `contents: write` | Download the verified bundle by ID, recompute every digest and publish |

The build job receives no secrets, does not persist checkout credentials and
has no access to the verification runner's files or job outputs. Only its
archive artifact ID crosses into verification. Verification and publication
execute only the helper from their own workflow revision. Their checkouts contain shared automation; caller source is read as data.

Plugin repositories must enable GitHub release immutability in their repository
settings before publishing. The helper checks `/repos/{owner}/{repo}/immutable-releases`
through the API before any Release write and fails clearly unless it reports
`enabled: true`. Server enforcement protects immutable release assets even if
another publisher makes the draft public after a draft precheck. Enabling the
setting does not lock previously published releases. The helper also requires the
Release's own `immutable: true` when it finds an existing public release and in
the response after publishing a draft. A public but mutable release fails with
an error requiring the repository owner to handle it; the workflow does not
change it or report it as published.

| Input | Contract |
| --- | --- |
| `ref` | Required. `vX.Y.Z` (including `-alpha.N`, `-beta.N`, `-rc.N`) for publication; a version tag or commit for a dry run |
| `publish` | Boolean, default `false` |
| `build` | Required shell command run at the source checkout; a quoted absolute output-directory argument is appended. It must create that directory with only the plugin ZIP archives |
| `ci_artifact` | Required exact artifact name from `ci.yml`; `${commit}` expands to the resolved full commit SHA. For matrix jobs, choose one exact matrix member |
| `runner` | Build runner, default `ubuntu-24.04`; source resolution, verification and publication use fresh `ubuntu-24.04` runners. Python 3.13 is supplied for source resolution, building and verification |

| Output | Contract |
| --- | --- |
| `published` | String `true` after publishing or verifying a complete public release with `immutable: true`; `false` for a dry run |
| `release_id` | Published GitHub Release ID, empty for a dry run |
| `tag` | Verified version tag, empty for an untagged commit dry run |

The release workflow must be pinned by its full commit SHA. Each trusted job
checks out `job.workflow_repository` at `job.workflow_sha`.
The source job checks `job.workflow_ref` is a full SHA pin and records it in
the receipt provenance. An embedded SHA-256 checks the helper before source
resolution, verification and publication; caller code cannot supply an
executable publisher. Verification passes the uploaded bundle's exact artifact
ID and a SHA-256 map for all release files through job outputs. Publication
recomputes and compares every file digest, validates the receipt and checks
`SHA256SUMS` before any Release write.

## Run and recover

1. Obtain successful default-branch push CI for the candidate commit. Set
   `ci_artifact` to its exact artifact name, including any matrix suffix.
2. Dispatch with that commit and `publish: false`. Inspect the
   `plugin-release-<run-id>-<attempt>` Actions artifact: `assets/` contains the
   verified ZIPs, deterministic `release-receipt.json` and `SHA256SUMS`.
   An untagged dry run reports the signed annotated tag still required.
3. Perform the plugin repository's manual archive acceptance. Create the signed
   annotated version tag on that same commit. Record the manual results and
   limits in a draft Release's notes, targeting the full commit SHA.
4. Dispatch with the version tag and `publish: true`. The workflow verifies the
   tag signature through GitHub, the manifest version and `plugin_api`, the CI
   source and archive set, then rebuilds and assembles the same release files.
   It creates a draft if none exists, uploads the receipt first, completes and
   verifies all assets, and publishes. The dependent job requests catalog
   reconciliation only after `published` is `true`.

A failed publication can be retried with **Re-run failed jobs**. If verification
already succeeded, the publish job downloads the same bundle artifact ID and
uses the saved digest outputs; it does not derive a new artifact name from the
retry's run attempt.

When verification runs again, a complete receipt in a draft freezes its
provenance. Verification validates the recorded historical CI run attempt
through the API: `.github/workflows/ci.yml`, event `push`, the repository's
default branch, status `completed`, conclusion `success` and the exact source
commit. It downloads the recorded artifact by ID, checks its digest and creation
within that attempt, compares it against the isolated build and reproduces the
same receipt and checksums. It refuses an invalid or unavailable recorded
attempt. A new CI attempt or a new release workflow pin does not change frozen
provenance. If receipt upload itself was incomplete, no source has been frozen
yet.

Missing assets are uploaded; matching completed assets are retained. Only
expected `starter` assets in a draft are removed and uploaded again. A completed
asset conflict requires inspecting the unpublished draft and its intended
source; the workflow does not replace it. If the recorded CI artifact expired
or was removed, delete the unpublished draft, obtain fresh successful CI
artifacts and dispatch again. This deliberately starts a new assembly with new
provenance. Published tags and assets remain immutable.

An already public release must report `immutable: true`. It is checked against
its frozen receipt and exact asset set and reported as published without writes.
Verification still rebuilds the archives; it can compare against the public
archive bytes after CI retention has expired. Notification failure needs only a
rerun of the notification job or a manual dispatch of `notify-catalog.yml`;
publication need not be repeated.

## Maintaining the shared workflow

Release logic lives in `scripts/plugin_release.py`, behind a four-operation
GitHub API interface. The offline tests use an in-memory API and inject failures
before and after draft creation, every asset upload, starter deletion and
publication. They also exercise provenance recovery, immutable public releases,
source checks, archive comparison, malicious build isolation, publish-only
retries and the workflow's helper boundary. The fake server fixes each release's
immutability when it is published: older mutable releases stay mutable when the
repository setting is enabled. It rejects mutations of immutable releases,
including visibility changes between draft prechecks and mutation requests.

When changing the helper, update `PLUGIN_RELEASE_SHA256` in the workflow to its
SHA-256. After the root README's environment setup, the repository CI commands
run the offline suite and verify that digest:

```sh
.build/venv/bin/python -m unittest discover -s tests
.build/venv/bin/python scripts/check-workflows.py
```

Release jobs have no shared concurrency group or caches. Callers must preserve
running and queued publications; coordinate simultaneous dispatches for a tag.

Frozen receipts from the original organization workflow remain valid provenance.
Recovery preserves their original workflow identity and bytes; newly assembled
receipts record this repository.
