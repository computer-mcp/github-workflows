# Offline organization evidence

`declaration/MAINTENANCE.md` contains the relevant Computer MCP maintenance
sections as test input. Its operational prose and illustrative paths are source
data. Live rules always come from the caller's requested organization revision.

`declaration/profile/catalog.json` uses the public profile's grouped catalog
shape. Its membership and About sentences are synthetic. `organization.json`
maps GET endpoints, including pagination parameters, to synthetic responses.
It covers public members, a private repository, a fork, an archived repository,
rulesets, merge queues, scoped Apps and credential names.

Tests mutate individual observations to check drift and unavailable responses.
Policy tests construct small Git histories in system temporary directories for
PR, push and merge-queue ranges; they also exercise signature/identity response
fixtures. Release and notification tests use their in-memory APIs and bounded
transport fixtures. None of these fixtures establishes live conformance.
