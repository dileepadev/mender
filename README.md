# Mender

**CI that fixes itself, and proves the fix.**

Mender watches your pipeline, reproduces failures in a sandbox, diagnoses the root cause, and opens a pull request containing both the fix and the regression test that proves it. When it cannot prove a fix, it opens an issue with its diagnosis instead of guessing.

> **Status: early development.** The whole loop runs end to end against a corpus of deliberately broken repositories, and the safety model below is enforced in code. What is missing is everything between a real CI system and the loop: log fetching, checkout at the failing commit, and a queue. Not yet usable against a live repository. See [TODO.md](TODO.md) for the current state, phase by phase.

---

## Why this exists

Coding agents are everywhere. Agents that **close the loop** are not.

Existing tools suggest fixes to a human at a keyboard, or report failures to a channel. The gap is everything between detection and a verified fix: reproducing the failure in isolation, finding the cause, authoring a minimal patch, writing the test that catches the regression, and confirming the suite still passes.

The distinction that matters is **suggestion versus verified outcome**. Wiring a model to a stack trace is easy. Proving the fix works — and declining to open a PR when it doesn't — is the engineering.

---

## The loop

```text
1. WATCH      pipeline webhook → failed run
2. CLASSIFY   parse logs → failure class + confidence
              └── unknown class → stop, report
3. REPRODUCE  sandbox: check out commit, run the failing test
              └── cannot reproduce → flaky path (re-run N times)
4. DIAGNOSE   agent receives failing test, trace, diff since last green, file context
5. FIX        minimal patch, constrained by blast-radius policy
6. PROVE      failing test must pass; full suite must not regress
              └── cannot prove → open an issue with the diagnosis, not a PR
7. SHIP       PR containing diagnosis, patch, regression test, before/after logs
```

Steps **3** and **6** are the product. The rest is plumbing.

---

## Safety model

An autonomous agent editing code needs hard limits, not prompt instructions.

**Never weakens a test to make CI green.** Patches that relax assertions, skip tests, or loosen thresholds are rejected by policy before they reach a PR. This is the failure mode that would make the whole idea dangerous, so it is enforced in code rather than requested in a prompt.

**Blast radius is declarative.** A policy file sets maximum files touched, maximum lines changed, path allowlists, and never-touch globs — CI configuration, secrets, migrations, workflow definitions. The agent proposes; policy disposes.

**Sandboxed reproduction.** Ephemeral containers, no network by default, hard timeouts, resource caps.

**Abstention is a feature.** A system that knows when to stop is worth more than one with a higher raw fix rate.

---

## Failure classes

Ordered by tractability. Early releases target the top of this list.

| Class | Status |
| --- | --- |
| Dependency drift and version breaks | Target |
| Flaky tests (quarantine and report, never edit assertions) | Target |
| Lint, format, and type errors | Target |
| Broken imports, missing config keys | Target |
| Failing assertions from a recent commit | Later |
| Logic bugs | Out of scope for now |
| Infrastructure and network flakes | Detect and report only |

Logic bugs are deliberately excluded early. Confident wrongness on subtle bugs is the fastest way to lose trust in an autonomous tool.

---

## Measurement

Mender will be evaluated against a curated corpus of real historical CI failures with known fixes, and the results published — including the unflattering ones.

- Repair rate by failure class
- **False-fix rate** — patches that passed CI but were wrong on human review
- PR acceptance rate (merged without modification)
- Mean time from failure to PR
- Cost per repair
- Abstention rate

The false-fix rate is published deliberately. It is the number that makes the others believable.

---

## Architecture

```text
mender/
├── mender.yaml                # repo configuration
├── src/mender/
│   ├── cli.py                 # one command per stage, plus `repair`
│   ├── config.py              # mender.yaml schema and the built-in protections
│   ├── models.py              # the values each stage hands the next
│   ├── repair.py              # the loop, and every exit from it
│   ├── report.py              # the record of one trip through the loop
│   ├── evals.py               # the corpus harness
│   ├── watch/                 # CI webhook and run ingestion
│   ├── classify/              # log parsers per language and framework
│   ├── sandbox/               # containerised reproduction
│   ├── policy/                # blast radius and the test-weakening detector
│   ├── diagnose/              # provider-agnostic agent layer
│   ├── patch/                 # applying and reverting under policy
│   ├── verify/                # the proof step
│   └── ship/                  # PR authoring with evidence
├── policies/                  # the default policy shipped with Mender
└── evals/corpus/              # historical failure corpus
```

Nothing in `diagnose/` can reach a repository without passing through
`policy/`, and `policy/` never sees the logs. An injection that successfully
confuses the agent still has to get a forbidden patch past code that was never
exposed to the text that did the confusing.

---

## Using it

```bash
uv sync --dev

mender validate                              # check a mender.yaml
mender classify build.log                    # what kind of failure is this?
mender reproduce build.log -w /path/to/repo  # can it be made to happen again?
mender repair build.log -w /path/to/repo     # the whole loop
mender eval                                  # run the corpus and print the numbers
```

`repair` writes its evidence package to a file by default. Add
`--publish github` to open a real pull request or issue, and `--agent anthropic`
to use a Claude-backed agent instead of the deterministic one — that needs the
optional extra (`uv sync --extra agent`) and an `ANTHROPIC_API_KEY`.

The sandbox defaults to Docker and falls back to running commands directly, with
a warning, when no daemon is available. The fallback has no container, no network
isolation, and no resource caps. Only point it at code you would run yourself.

---

## Roadmap

### Stage 0 — Proof of concept

- [x] Webhook ingestion of failed runs
- [x] Sandbox reproduction of a failing test at a given commit
- [x] Log classifier for the first three failure classes
- [x] Policy engine and the test-weakening detector, with an adversarial suite
- [x] Diagnosis and minimal patch generation under policy
- [x] Verification step and PR authoring with evidence
- [x] Issue-instead-of-PR path when confidence is low
- [x] Eval corpus and harness, run in CI
- [ ] Log fetching and checkout at the failing commit
- [ ] First Mender-authored PR merged into a real repository
- [ ] Benchmark against a corpus of real historical failures; publish results

The phase-by-phase plan, with exit criteria, is in [TODO.md](TODO.md).

### Stage 1 — Installable

- [ ] Installable app any repository can add
- [ ] Configurable languages, test commands, and blast-radius limits
- [ ] Multi-language support

### Stage 2 — Fleet

- [ ] Recurring-failure analytics, mean time to repair, fix acceptance
- [ ] Per-repository learned patterns
- [ ] Team policy controls

---

## Author

Built by [Dileepa Bandara](https://dileepa.dev) — AI Engineer working on agents, MCP, and retrieval systems.
