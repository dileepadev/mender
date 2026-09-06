# Changelog

All notable changes to this project are documented in this file.

Changes are organized into the following categories:

- **Added:** New features or functionality introduced to the project.
- **Changed:** Modifications to existing functionality that do not add new features.
- **Fixed:** Bug fixes that resolve issues or correct unintended behavior.
- **Removed:** Features or components that have been removed from the project.

## [Unreleased]

### Added

- **The repair loop, end to end.** `mender repair` takes a failed run from logs to a pull request or an abstention, with an exit at every stage.
- **Sandbox.** A `Runner` interface with a Docker backend — no network, memory, CPU and process caps, all capabilities dropped, guaranteed teardown — and a local backend for development that documents exactly what it gives up. Reproduction distinguishes a real failure from a flaky one and never repairs the latter.
- **Classifier.** Ordered pattern rules covering dependency drift, broken imports, lint, format, type errors, missing configuration, assertions, and infrastructure, with confidence scoring and an ambiguity penalty. An unrecognised failure produces `UNKNOWN` and a full stop.
- **Policy engine.** Blast-radius limits, path allowlists, never-touch globs, and an AST-level test-weakening detector that rejects deleted tests, skip and xfail markers, removed or relaxed assertions, widened tolerances, dropped parametrised cases, and lowered coverage thresholds. Backed by an adversarial suite of deliberately cheating patches that runs in CI.
- **Agent layer.** A provider-agnostic `DiagnosisAgent` protocol, a deterministic agent for the failure classes with one correct repair, and a Claude-backed agent behind an optional `agent` extra. Log content is fenced and labelled as untrusted data in every prompt.
- **Proof step.** The failing check passes, a test demonstrably catches the bug, and the full suite is compared against a pre-patch baseline. Anything less is an abstention.
- **Evidence package.** Pull requests and issues carrying the diagnosis, patch, regression test, proof, before and after logs, the policy limits that applied, and the cost.
- **Webhook receiver.** `mender watch` verifies signatures before reading a payload and records failed runs.
- **Eval corpus and harness.** `mender eval` runs five broken repositories with known correct outcomes and reports repair rate, false-fix rate, abstention rate, mean time, and cost.
- CLI commands: `classify`, `reproduce`, `repair`, `watch`, and `eval`.
- `policies/default.yaml`, pinned to the code defaults by a test.

### Changed

- `README.md`, `docs/development.md`, `docs/how-it-works.md`, `docs/safety-and-limits.md`, and `policies/README.md` now describe what exists rather than what is planned.
- `TODO.md` records the build plan phase by phase, each with an exit criterion.

<!-- e.g., -->
<!-- Unreleased -->
<!-- v2.0.0 -->
<!-- v1.1.0 -->
<!-- v1.0.0 -->
<!-- v0.0.1 -->

[Unreleased]: https://github.com/dileepadev/mender/branches
