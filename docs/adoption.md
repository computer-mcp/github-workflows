# Adopting shared automation

Use one reviewed full `github-workflows` commit SHA for the workflows and action
below. Use a separate full `.github` SHA for the rule/catalog declaration. Each
consumer owns its pull request; required checks are selected only after their
actual contexts have been observed. Shared changes are independently versioned.

## Consumer files

The following inventory describes the callers present during this migration.
Replace only the specified shared reference and retain repository-specific inputs,
repository guards, secrets and output mappings. All paths are repository-relative.

| Repository | File | Change |
| --- | --- | --- |
| `plugin-claude` | `.github/workflows/ci.yml` | Pin `plugin-runtime.yml` here; remove brand job and its dependency references; aggregate remaining validation jobs |
| `plugin-claude` | `.github/workflows/release.yml` | Pin `plugin-release.yml` here; keep `ref`, `publish`, `build`, `ci_artifact` and notification dependency |
| `plugin-claude` | `.github/workflows/notify-catalog.yml` | Pin `computer-mcp/github-workflows/actions/notify-catalog` |
| `plugin-cursor` | `.github/workflows/ci.yml` | Pin runtime here; remove brand job/dependencies; aggregate validation |
| `plugin-cursor` | `.github/workflows/release.yml` | Pin release here with existing inputs |
| `plugin-cursor` | `.github/workflows/notify-catalog.yml` | Pin notification action here |
| `plugin-trae` | `.github/workflows/ci.yml` | Pin runtime here; remove brand job/dependencies; aggregate validation |
| `plugin-trae` | `.github/workflows/release.yml` | Pin release here with existing inputs |
| `plugin-trae` | `.github/workflows/notify-catalog.yml` | Remove; the private plugin has no catalog notification |
| `plugin-computer-use` | `.github/workflows/ci.yml` | Remove brand job/dependencies; aggregate validation |
| `plugin-computer-use` | `.github/workflows/release.yml` | Pin release here with existing inputs |
| `plugin-computer-use` | `.github/workflows/notify-catalog.yml` | Pin notification action here |
| `plugin-swift-format` | `.github/workflows/ci.yml` | Remove brand job/dependencies; aggregate validation |
| `plugin-swift-format` | `.github/workflows/release.yml` | Pin release here with existing inputs |
| `plugin-swift-format` | `.github/workflows/notify-catalog.yml` | Pin notification action here |
| `plugin-codex` | `.github/workflows/ci.yml` | Remove brand job/dependencies; aggregate validation |
| `plugin-codex` | `.github/workflows/notify-catalog.yml` | Pin notification action here |
| `computer-mcp` | `.github/workflows/ci.yml` | Remove brand job/dependencies; aggregate validation; retain `merge_group` coverage |
| `apple-cli` | `.github/workflows/ci.yml` | Remove brand job/dependencies; aggregate validation |
| `computer-mcp.github.io` | `.github/workflows/ci.yml` | Remove brand job/dependencies; aggregate validation |
| `.github` | `.github/workflows/ci.yml` | Call `organization.yml` with the reviewed declaration revision; replace migrated implementation tests with thin shared calls |

Each of these repositories also adds `.github/workflows/source-policy.yml`, using
the separate PR-title-aware caller in the root README. Its validation caller runs
on opened/synchronize/reopened PRs, default-branch pushes and its declared manual
triggers. Policy includes PR title edits. The host also runs both on merge queues.
Use the actual maintained default branch for a fork.

`homebrew-tap` and the maintained SDK fork have no old reusable references in the
inspected checkout inventory; their owners adopt policy and validation callers
under their own existing CI and upstream compatibility requirements. This is not
evidence of their live workflow state.

The Codex plugin retains its native artifact-promotion release implementation as
owned by shared VERSIONING. Its release caller is not converted to reproducible
archive rebuilding.

## Shared owners

The organization `.github` repository no longer contains the migrated
implementations (the plugin runtime and release workflows, `PluginRuntime/`,
the plugin and settings scripts with their tests and operating guide) or the
brand-check workflow. A member that has not moved yet keeps working because it
pins an earlier `.github` commit, which still resolves. `.github` keeps rules,
catalog data, documentation and thin callers, and its README and MAINTENANCE
link here for operation.

The website owner retires `.github/actions/notify-catalog/` and the migrated
notification transport tests after callers move. Its `pages.yml` receiver,
catalog validation and deployment implementation keep their existing contracts.
Update any local tests/documentation that refer to the retired action location.

## Adoption requirements

- The `.github` declaration used online contains both the accepted source rules
  and `profile/catalog.json`. Fixtures are never a live fallback.
- MAINTENANCE stores catalog credentials only in the five public plugins.
  `plugin-trae` is private and outside the catalog, so adoption removes its
  notification caller.
- CI runs the organization check with `scope: membership`. The `full` scope
  needs administrative reads and runs from an organization owner's `gh` login;
  MAINTENANCE allows no additional organization-read secret. Inaccessible
  observations exit nonzero as unknown.
- A new pin is adopted after one representative consumer run at that pin on
  GitHub Actions; local fixture or archived-source runs do not replace it.
  Retain running and queued releases during the rollout.

No additional source-policy rule is required for this implementation. The checker
does not infer new allowed identities, contributor restrictions or content bans
from the reference implementation. Changes to rules belong in MAINTENANCE first.
