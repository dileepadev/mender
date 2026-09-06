# Glossary

Every technical term used across Mender's documentation, defined plainly. No prior CI knowledge assumed.

Terms are grouped by topic rather than alphabetised, so related ideas sit together. If you are looking for one specific word, use your browser's find function.

## Table of Contents

- [The basics](#the-basics)
- [Tests](#tests)
- [Things that break](#things-that-break)
- [How Mender works](#how-mender-works)
- [Safety terms](#safety-terms)
- [Measurement terms](#measurement-terms)

## The basics

**Repository (repo)**
A project's folder of code, plus the complete history of every change ever made to it.

**Commit**
One saved change to the code, with a message describing it and a unique ID like `a1b2c3d`. The history of a repository is a chain of commits.

**Branch**
A parallel line of work. You branch off the main code, make changes safely, and merge back when ready. Meanwhile nobody else is disturbed.

**Merge**
Folding a branch's changes back into the main code.

**Pull request (PR)**
A proposal to merge a branch, opened for review. Teammates read it, comment, and approve or reject. This is where code review happens, and it is the only way Mender's changes ever reach a codebase.

**Diff**
The precise list of what changed between two versions — which lines were added, removed, or altered. Usually shown with `+` for additions and `-` for removals.

**Patch**
A diff intended as a fix. When Mender "writes a patch," it produces a specific set of line changes.

## Tests

**Test**
A small program whose only job is to check that another program behaves correctly. It runs the real code with known inputs and asserts the output is what it should be.

**Assertion**
The actual check inside a test — "this value must equal that value." When an assertion is false, the test fails.

**Test suite**
All the tests in a project, run together.

**Regression**
When something that used to work stops working. A **regression test** is a test written specifically to catch a bug you already fixed, so it can never silently come back. When Mender fixes something, it writes one of these — that is the "proves the fix" part.

**Coverage**
How much of the code is actually exercised by tests, as a percentage. Higher is generally better. Lowering a coverage threshold to make a check pass is one of the things Mender's policy blocks.

## Things that break

**CI (continuous integration)**
The practice of automatically checking every change to the code, immediately, rather than finding out later that something broke.

**Pipeline**
The automated checklist CI runs: build the code, run the tests, check the formatting, check the types. Sometimes called a *build* or a *workflow*.

**Green / red**
A pipeline is **green** when every check passed and **red** when something failed. Red blocks the change from merging.

**Linter**
A tool that checks code style and catches suspicious patterns — unused variables, inconsistent formatting, likely mistakes. `ruff` is the Python linter Mender targets first.

**Type error**
A mistake where the wrong *kind* of value is used — passing text where a number was expected. Caught by a type checker like `mypy` before the code ever runs.

**Import error**
Code asking for something that is not there — usually because it was renamed, moved, or deleted somewhere else. `ImportError` and `ModuleNotFoundError` are the common Python forms.

**Dependency**
External code your project relies on. Most projects have hundreds.

**Dependency drift**
When an external dependency releases a new version that changes behaviour, and your project breaks even though nobody on your team changed anything. A common and deeply annoying cause of red pipelines.

**Lockfile**
A file recording the exact version of every dependency, so everyone gets identical versions. Changing it changes what code actually runs, which is why Mender treats it carefully.

**Flaky test**
A test that fails sometimes and passes other times without the code changing — usually due to timing, ordering, or randomness. Flaky tests are corrosive: they train teams to ignore red pipelines. Mender detects and reports them but never edits them, because there is usually nothing in the test to fix.

**Quarantine**
Marking a flaky test so it stops blocking the pipeline while remaining visible and tracked. The point is to keep the team unblocked without pretending the problem is solved.

## How Mender works

**The loop**
Mender's seven steps: watch, classify, reproduce, diagnose, fix, prove, ship. Described in [how-it-works.md](how-it-works.md).

**Webhook**
An automatic message one system sends another when something happens. Mender's CI provider sends a webhook the moment a run fails, so Mender does not have to keep asking.

**Failure class**
The category a failure falls into — lint error, type error, broken import, dependency drift, flaky test. Classification determines whether Mender proceeds at all.

**Confidence score**
How certain Mender is about its own classification or diagnosis. Below a configured threshold, it stops and reports instead of acting.

**Sandbox**
A clean, isolated, disposable environment where Mender rebuilds the broken state and runs code. No network access by default, hard time limits, capped memory and CPU, and destroyed entirely when finished. Nothing that happens inside can touch the real system.

**Container**
The technology behind the sandbox — a lightweight isolated box with its own filesystem and dependencies, created and destroyed in seconds.

**Reproduction**
Making a failure happen again on purpose, in the sandbox. If Mender cannot reproduce a failure, it will not attempt to fix it.

**Diff since last green**
The changes made since the last time the pipeline fully passed. The cause of a new failure is very often somewhere in here, which makes this the single most useful piece of context Mender gives the agent.

**Verification / proof**
The step where Mender demonstrates the fix works: the failing test passes, the regression test genuinely catches the bug, and nothing else broke. Without all three, no pull request.

**Abstention**
Deliberately declining to act. When Mender cannot prove a fix, it opens an issue containing its diagnosis instead of a pull request containing a guess.

## Safety terms

**Blast radius**
How much damage a change could possibly do. Mender's policy caps it explicitly — maximum files touched, maximum lines changed, which paths are allowed.

**Policy**
A configuration file defining the hard limits on what Mender may change. Enforced in code, before a patch can become a pull request. The agent proposes; policy disposes.

**Allowlist / never-touch globs**
Path patterns that are explicitly permitted, and patterns that are permanently forbidden — CI configuration, workflow files, secrets, database migrations.

**Test weakening**
Making a test easier to pass instead of fixing the underlying problem: deleting it, skipping it, relaxing an assertion, widening a numeric tolerance, lowering a coverage threshold. This turns a pipeline green while making the software worse, and it is the single most dangerous thing an autonomous agent could do here. Mender blocks it structurally. See [safety-and-limits.md](safety-and-limits.md).

**Migration**
A script that changes the structure of a database. Difficult to reverse safely, so permanently off limits.

**Prompt injection**
An attack where malicious instructions are hidden inside content an AI model reads — for example, text planted in a log file that tries to convince the agent to ignore its rules. On public repositories, logs are attacker-controlled, so Mender treats all log content as untrusted data rather than instructions.

## Measurement terms

**Repair rate**
The share of failures Mender successfully fixed, broken down by failure class.

**False-fix rate**
The share of patches that passed CI but were judged wrong by a human reviewer. This is the number that matters most — a fix that satisfies the tests while being incorrect is worse than no fix at all. Mender publishes this deliberately, because it is what makes the other numbers believable.

**PR acceptance rate**
The share of Mender's pull requests merged without modification.

**Abstention rate**
How often Mender declines to act. A healthy number, not a failure metric.

**Mean time to repair (MTTR)**
Average elapsed time from a failure appearing to a fix being available.

**Eval corpus**
A curated collection of real historical CI failures with known correct fixes, used to measure Mender objectively rather than by anecdote.
