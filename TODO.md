# TODO

This file tracks tasks, improvements, and features planned for upcoming updates or releases of this repository.  

>[!Note]
> This list is **not exhaustive** and may change over time. Items are not necessarily in priority order.

The work is sequenced in phases. Each has an **exit criterion** — the one thing
that has to be demonstrably true before the phase is done. The order is not
arbitrary: the policy engine is built *before* patch generation, so there is
never a window in which patches can be produced without something inspecting
them.

## Stage 0 — Proof of concept

### Phase 0 — Configuration and CLI ✅

- [x] `mender.yaml` schema, strict validation, unknown keys rejected
- [x] Built-in never-touch globs a repository can add to but never remove
- [x] `mender validate`

**Exit criterion:** a repository can declare how Mender should treat it, and a typo in a safety limit fails loudly.

### Phase 1 — The eval corpus ✅

- [x] Case format: `case.yaml`, a broken `repo/`, and the `logs.txt` CI produced
- [x] Harness that copies each case out, runs the whole loop, and scores it
- [x] Repair rate, **false-fix rate**, abstention rate, mean time, cost
- [x] Five cases: incomplete rename, unused import, assertion, unknown signature, will-not-reproduce
- [x] `mender eval`, wired into CI

**Exit criterion:** every downstream phase is measured against cases with known answers rather than against anecdote.

### Phase 2 — The sandbox ✅

- [x] `Runner` interface; nothing executes outside it
- [x] `DockerRunner`: no network, memory/CPU/PID caps, all capabilities dropped, no privilege escalation
- [x] Guaranteed teardown — on exit, on timeout, on crash
- [x] `LocalRunner` for development, documented for exactly what it gives up
- [x] Reproduction, with the flaky path when a failure will not happen again
- [x] `mender reproduce`

**Exit criterion:** a failure can be made to happen again on purpose, inside something disposable.

### Phase 3 — The classifier ✅

- [x] Ordered pattern rules per failure class, with root-cause precedence
- [x] Confidence scoring, with a penalty when a log is ambiguous
- [x] Failing-test extraction in both pytest output layouts
- [x] Support levels: target, later, report-only, unsupported
- [x] `mender classify`

**Exit criterion:** an unrecognised failure produces `UNKNOWN` and a full stop, not a guess.

### Phase 4 — The policy engine ✅

- [x] Glob matching where `*` never crosses a directory separator
- [x] Blast radius: max files, max lines, path allowlist, never-touch globs
- [x] **Test-weakening detector**, at the AST level
- [x] The adversarial suite — hand-written cheating patches, all rejected, run in CI
- [x] Every rejection names the specific rule that was broken
- [x] `policies/default.yaml`, pinned to the code defaults by a test

**Exit criterion:** the detector rejects every cheat in `tests/policy/test_weakening_adversarial.py`, and weakening it turns Mender's own pipeline red.

### Phase 5 — Diagnosis and patch generation ✅

- [x] `DiagnosisAgent` protocol; no vendor SDK reachable from the loop
- [x] Context assembly, including the diff since the last green run
- [x] Untrusted log content fenced and labelled as data in every prompt
- [x] `HeuristicAgent` — deterministic repairs for incomplete renames and unused imports
- [x] `AnthropicAgent` — Claude-backed, an optional extra, never needed by the test suite
- [x] Whole-file patches, path traversal refused at the model boundary
- [x] Retry within a cost budget, with the rejection reason fed back

**Exit criterion:** a patch reaches the policy engine before it reaches anything else.

### Phase 6 — The proof step ✅

- [x] The failing check passes with the patch applied
- [x] The regression test fails without the fix and passes with it
- [x] The full suite is compared against a pre-patch baseline; no new failures
- [x] Abstention when any of the three does not hold

**Exit criterion:** a fix that cannot be demonstrated does not ship.

### Phase 7 — The evidence package ✅

- [x] Pull request body: diagnosis, patch, regression test, proof, before/after logs, policy limits, cost
- [x] Issue body for every abstention, including what Mender *would* have changed
- [x] Flaky reports that say why the test is not edited

**Exit criterion:** a reviewer can judge a Mender pull request in a few minutes without opening the repository.

### Phase 8 — Webhook ingestion ✅

- [x] Signature verification before the payload is read
- [x] `workflow_run`, `check_run`, and `check_suite` events
- [x] Anything that is not a completed, failed run is discarded
- [x] `mender watch`

**Exit criterion:** a hostile payload cannot get past the signature check or crash the receiver.

### Phase 9 — Shipping ✅

- [x] `Publisher` interface
- [x] `DryRunPublisher` — the default; nothing reaches a repository by accident
- [x] `GitHubPublisher` — branch, commit, push, pull request, or an issue on abstention
- [x] Mender never merges its own work

**Exit criterion:** `mender repair` runs the whole loop and produces something a human can act on.

## What is left in Stage 0

- [ ] Log fetching — the webhook says a run failed; something has to retrieve its output
- [ ] Checkout at the failing commit, rather than being handed a workspace
- [ ] Wire the receiver's inbox into the repair loop as a queue
- [ ] Dependency-drift repairs: read the lockfile, propose a pin, prove it
- [ ] Type-error repairs beyond what the classifier already recognises
- [ ] A kill switch: a label or config flag that halts Mender on a repository immediately
- [ ] Grow the corpus from real historical failures, not just hand-built ones
- [ ] First Mender-authored pull request merged into a real repository
- [ ] Benchmark against the corpus and publish the results, including the unflattering ones

## Stage 1 — Installable

- [ ] Installable app any repository can add
- [ ] A language adapter interface — test command, log parsers, patch conventions
- [ ] Multi-language support beyond Python
- [ ] Hosted runner with per-repository isolation

## Stage 2 — Fleet

- [ ] Recurring-failure analytics, mean time to repair, fix acceptance
- [ ] Per-repository learned patterns
- [ ] Team policy controls

## Deliberately out of scope

Recorded here so they do not quietly creep back in. The reasoning is in
[docs/safety-and-limits.md](docs/safety-and-limits.md).

- **Logic bugs.** Confident wrongness on subtle bugs is the fastest way to lose trust.
- **Auto-merging.** A human approves every change, without exception.
- **Editing CI configuration.** The one place an agent could disable its own guardrails.
- **"Fixing" flaky tests.** There is usually nothing in the test to fix; editing it hides the problem.
- **Infrastructure and network flakes.** Detect and report only.
- **Self-hosted runners.** The sandbox threat model differs materially and needs separate work.
