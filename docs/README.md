# Mender documentation

**CI that fixes itself, and proves the fix.**

These docs assume no prior experience with CI, testing, or AI agents. Everything is explained where it first appears.

> **Status: early development.** The whole loop runs end to end against a corpus of deliberately broken repositories, and the safety model is enforced in code. What is missing is everything between a real CI system and the loop — log fetching, checkout at the failing commit, a queue — so this is not yet usable against a live repository. [TODO.md](../TODO.md) tracks the state phase by phase.

## Start here

| If you... | Read |
| --- | --- |
| Have never worked with CI and want to know what this is | [What is Mender?](what-is-mender.md) |
| Want to see the repair loop step by step, with a real example | [How it works](how-it-works.md) |
| Think letting an agent edit code sounds dangerous | [Safety and limits](safety-and-limits.md) |
| Hit a term you don't recognise | [Glossary](glossary.md) |
| Have a specific or sceptical question | [FAQ](faq.md) |
| Want to set up the project locally | [Development setup](development.md) |
| Want to help build it | [TODO](../TODO.md) and [CONTRIBUTING](../CONTRIBUTING.md) |
| Want to know how it is measured | [Eval corpus](../evals/README.md) |

**Reading in order?** [What is Mender?](what-is-mender.md) → [How it works](how-it-works.md) → [Safety and limits](safety-and-limits.md) → [FAQ](faq.md), with the [glossary](glossary.md) open in another tab.

## The short version

When a team's automated checks break — a bad import, a formatting violation, a dependency that changed underneath them — somebody has to stop working, read the logs, find the cause, write the fix, and confirm nothing else broke.

Mender takes that round trip. It reproduces the failure in an isolated sandbox, diagnoses the cause, writes a minimal patch, proves the patch works, and opens a pull request containing the evidence.

When it cannot prove the fix, it opens an issue with its diagnosis instead of guessing.

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

## The three ideas that matter

**Suggestion versus verified outcome.** Wiring a model to a stack trace is easy. Proving the fix works — and declining to open a pull request when it doesn't — is the engineering.

**Rules in code, not rules in prompts.** Anything that must never happen is enforced by code that inspects the patch, before it can become a pull request. A model can reason its way around an instruction. It cannot reason its way around a rejected patch.

**Abstention is a feature.** A system that knows when to stop is worth more than one with a higher raw fix rate. Mender is designed to stop more often than it ships.

## Also in this repository

- [README](../README.md) — project overview, architecture, and roadmap
- [TODO](../TODO.md) — the build plan, phase by phase, with exit criteria
- [Policies](../policies/README.md) — the blast-radius limits and the test-weakening detector
- [Eval corpus](../evals/README.md) — the failures Mender is measured against
- [CONTRIBUTING](../CONTRIBUTING.md) — how to contribute
- [SECURITY](../SECURITY.md) — security policy and reporting
- [CHANGELOG](../CHANGELOG.md) — record of changes
