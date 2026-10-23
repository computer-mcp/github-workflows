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
| `plugin-trae` | `.github/workflows/notify-catalog.yml` | Pin notification action here after resolving credential scope below |
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

The organization `.github` owner retires the migrated implementations only after
consumers have moved: the plugin runtime/release workflows, `PluginRuntime/`,
`Scripts/plugin-runtime.py`, `Scripts/plugin_release.py`, `Scripts/check-settings.py`
and their tests and operating guide. Its README and MAINTENANCE operational
command link to this repository. It retains rules, catalog data, documentation
and thin workflow callers. Brand-check callers are removed under the accepted
presentation standard; no brand-check workflow is provided here.

The website owner retires `.github/actions/notify-catalog/` and the migrated
notification transport tests after callers move. Its `pages.yml` receiver,
catalog validation and deployment implementation keep their existing contracts.
Update any local tests/documentation that refer to the retired action location.

## Adoption prerequisites and owner decisions

- The `.github` declaration used online must contain both the accepted source
  rules and `profile/catalog.json`. Fixtures are never a live fallback.
- The current MAINTENANCE App table lists catalog credential storage in five
  plugins, while `plugin-trae` also has a notification caller. Its owner must
  either declare and provision that scope or retire that notification caller.
  This repository does neither.
- Full online settings checks require administrative read access and access to
  App installation repository lists. MAINTENANCE currently allows only the
  listed App credentials, not an additional organization-read secret. Decide
  the approved execution/credential arrangement before unattended online CI;
  local runs can use an organization owner's existing `gh` login. Inaccessible
  observations exit nonzero as unknown.
- Run one representative consumer at the candidate pin before broad rollout.
  Local fixture/archived-source runs do not replace a GitHub Actions run at that
  pin. Retain running and queued releases during the rollout.

No additional source-policy rule is required for this implementation. The checker
does not infer new allowed identities, contributor restrictions or content bans
from the reference implementation. Changes to rules belong in MAINTENANCE first.
