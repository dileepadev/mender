# How Mender works

This page walks through Mender's repair loop one step at a time, then follows a single real failure all the way from a red pipeline to a finished pull request.

If terms like *pipeline*, *sandbox*, or *flaky test* are unfamiliar, read [what-is-mender.md](what-is-mender.md) first or check the [glossary](glossary.md).

## Table of Contents

- [The loop at a glance](#the-loop-at-a-glance)
- [The seven steps](#the-seven-steps)
- [A worked example](#a-worked-example)
- [Where the loop can stop early](#where-the-loop-can-stop-early)

## The loop at a glance

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

Steps **3** and **6** are the product. The rest is plumbing. Everything else in this system exists to make reproduction and proof possible.

## The seven steps

### 1. Watch

Mender listens for a signal from your CI system saying a run failed. This arrives as a **webhook** — a message your CI provider sends automatically when something happens, rather than Mender constantly asking "anything broken yet?"

The signal carries the essentials: which repository, which commit, which job failed, and where to find the logs.

**Produces:** a failed run record.

### 2. Classify

Mender reads the logs and decides *what kind* of failure this is — a formatting violation, a type error, a broken import, a dependency that changed underneath the project.

It also produces a **confidence score**. This matters more than it sounds. If Mender cannot tell what kind of failure it is looking at, it stops here and reports what it saw. There is no fallback to guessing.

**Produces:** a failure class and a confidence score, or `UNKNOWN` and a full stop.

### 3. Reproduce

This is the first half of the product.

Mender builds a **sandbox** — a clean, throwaway, isolated environment, with no network access, hard time limits, and capped memory and CPU. Inside it, Mender checks out the exact commit that failed, installs the exact dependencies, and runs the failing test.

Two outcomes matter:

- **The failure happens again.** Good. It is real and understood. Continue.
- **The failure does not happen again.** The test is probably **flaky** — it fails sometimes for reasons unrelated to the code. Mender re-runs it several times to measure how often, then reports it for quarantine. It does not "fix" a flaky test, because there is usually nothing there to fix, and editing the test to stop it failing would be hiding the problem.

Everything downstream depends on this step. You cannot prove you fixed something you were never able to make happen on purpose.

**Produces:** a confirmed, reproducible failure — or a flaky-test report.

### 4. Diagnose

Now the agent gets involved, and it gets a carefully assembled packet:

- The failing test and its output
- The full error trace
- **The diff since the last green run** — the changes made since the last time everything passed. The cause is very often in here.
- The relevant slices of the surrounding files

That "diff since last green" is doing a lot of work. It narrows a haystack of thousands of files down to the handful that actually changed since things last worked.

**Produces:** a root-cause explanation and a proposed change.

### 5. Fix

The agent writes a patch — and the patch is immediately checked against a **policy** before it is allowed to go anywhere.

The policy is a file that sets hard limits: how many files may be touched, how many lines may change, which paths are allowed, and which are permanently off limits. It also runs a specific check for the dangerous case: **a patch that weakens a test to make the failure go away is rejected outright.**

The agent proposes. The policy disposes. These limits live in code, not in the prompt — an agent can talk itself past an instruction, but it cannot talk itself past a rejected patch. See [safety-and-limits.md](safety-and-limits.md).

**Produces:** a minimal patch that satisfies policy, or a rejection.

### 6. Prove

The second half of the product, and the step that separates Mender from a suggestion engine.

Back in a clean sandbox, Mender confirms three things:

1. **The originally failing check now passes.** The obvious one. For a test failure that is the test suite; for a lint or type failure it is the linter or the type checker, because those are the checks that were actually red.
2. **A test genuinely catches this bug.** The regression test must fail *without* the patch and pass *with* it. A test that passes either way proves nothing.
3. **Nothing else broke.** The full suite is compared against the pre-patch baseline. No new failures.

If any of those three does not hold, the loop stops and routes to the abstention path. Mender opens an issue containing its diagnosis rather than a pull request containing a guess.

**One case has no new test, and that is correct.** When the failing check is a
linter or a type checker, that tool *is* a check which fails on the unpatched
code and passes on the patched code — it already does what a regression test
would do. Mender writes no new test there and says so in the evidence package,
naming the check that plays the role. It never skips check 2; it records what
satisfied it.

**Produces:** verified proof, or an abstention.

### 7. Ship

Mender opens a pull request containing the complete evidence package:

- What was wrong and why
- The patch itself
- The regression test
- Before and after logs
- Which policy limits applied
- What the repair cost

A human reads it and decides. Mender never merges its own work.

**Produces:** a pull request a reviewer can actually evaluate.

## A worked example

Here is a small, extremely common failure, followed end to end.

### The setup

A project has a helper function:

```python
# app/utils.py
def format_price(amount):
    return f"${amount:.2f}"
```

A developer decides `format_currency` is a better name and renames it. They update most of the places that call it — but miss one, in `app/checkout.py`. They push the change.

### Step 1 — Watch

The pipeline goes red. Mender receives the webhook: repository, commit `a1b2c3d`, job `pytest`, logs attached.

### Step 2 — Classify

Mender parses the log and finds:

```text
ImportError: cannot import name 'format_price' from 'app.utils'
```

Class: **broken import**. Confidence: high — this error message is unambiguous. Continue.

### Step 3 — Reproduce

Mender spins up a clean container, checks out commit `a1b2c3d`, installs dependencies, and runs:

```bash
pytest tests/test_checkout.py
```

The same `ImportError` appears. The failure is real and reproducible, not flaky. Continue.

### Step 4 — Diagnose

The agent receives the error, the trace, and the diff since the last green run. The diff shows it plainly:

```diff
- def format_price(amount):
+ def format_currency(amount):
```

A grep across the repository shows `format_price` is still referenced in exactly one place: `app/checkout.py`. Root cause: an incomplete rename.

### Step 5 — Fix

The proposed patch is one line:

```diff
# app/checkout.py
- from app.utils import format_price
+ from app.utils import format_currency

- return format_price(total)
+ return format_currency(total)
```

Policy check: 1 file touched, 4 lines changed, path is in the allowlist, no test files modified, no assertions weakened. **Approved.**

Note what Mender did *not* do. Renaming the function back to `format_price` would also make CI green, and it would be wrong — it would undo a deliberate decision. The minimal patch that respects the author's intent is to finish the rename.

### Step 6 — Prove

In a clean sandbox:

1. `tests/test_checkout.py` now passes. ✅
2. Mender adds a regression test that imports and calls the checkout path. Run against the *unpatched* code, it fails. Run against the patched code, it passes. The test genuinely catches this bug. ✅
3. The full suite runs: 247 passed, 0 failed. The baseline before the patch was 246 passed, 1 failed. No new failures. ✅

All three hold. Continue.

### Step 7 — Ship

Mender opens a pull request:

> **Fix incomplete rename of `format_price` → `format_currency`**
>
> **Diagnosis:** commit `a1b2c3d` renamed `format_price` to `format_currency` in `app/utils.py` but left one call site in `app/checkout.py`, causing an `ImportError` at collection time.
>
> **Patch:** updated the import and call site in `app/checkout.py` (1 file, 4 lines).
>
> **Regression test:** `tests/test_checkout.py::test_checkout_formats_total` — verified failing before the patch, passing after.
>
> **Suite:** 247 passed, 0 failed (baseline: 246 passed, 1 failed).
>
> Before and after logs attached. Cost: $0.04.

A human reads it, agrees, and merges. Total elapsed time: a few minutes, and nobody had to stop what they were doing.

## Running it yourself

Each stage is its own command, which matters because the stages where Mender
decides whether to act at all should be inspectable on their own:

```bash
mender classify build.log                    # what kind of failure is this?
mender reproduce build.log -w /path/to/repo  # can it be made to happen again?
mender repair build.log -w /path/to/repo     # all seven steps
```

`repair` prints its trace as it goes — one line per stage, ending in the
outcome — and writes the evidence package to a file. Nothing reaches a
repository unless you add `--publish github`.

## Where the loop can stop early

Mender is designed to stop more often than it ships. Every one of these is a success, not a failure.

| Step | Stops when | What happens instead |
| --- | --- | --- |
| 2. Classify | The failure class is unrecognised | Report what was seen, no further action |
| 3. Reproduce | The failure will not happen again | Flaky-test report and quarantine recommendation |
| 5. Fix | The patch violates policy | Rejection, with the specific rule that was broken |
| 5. Fix | The patch weakens a test | Hard rejection — this one is never negotiable |
| 6. Prove | The regression test does not catch the bug | Abstain; issue with diagnosis |
| 6. Prove | Another test broke | Abstain; issue naming the newly broken test |
| Any | Confidence is below threshold | Issue with diagnosis, not a pull request |

**Abstention is a feature.** The whole idea only works if the pull requests Mender does open are trustworthy — and that is only true if it declines to open the ones it cannot stand behind.
