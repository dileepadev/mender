# What is Mender?

**In one sentence:** Mender is a robot teammate that notices when a project's automated checks break, works out why, writes a fix, proves the fix actually works, and then asks a human to approve it.

This page assumes you have never worked with CI before. Every term is explained where it first appears, and all of them are collected in the [glossary](glossary.md).

## Table of Contents

- [Start with the problem](#start-with-the-problem)
- [An analogy](#an-analogy)
- [What makes Mender different](#what-makes-mender-different)
- [The hard part is not the fixing](#the-hard-part-is-not-the-fixing)
- [What Mender will not do](#what-mender-will-not-do)
- [Where to go next](#where-to-go-next)

## Start with the problem

### What is CI?

When people build software together, they need a way to catch mistakes before those mistakes reach real users. So they set up an automated checklist that runs every single time anyone changes the code.

That checklist is called a **pipeline**. The practice of running it constantly is called **continuous integration**, usually shortened to **CI**.

A typical pipeline asks a handful of questions:

- Does the code still build?
- Do all the **tests** still pass? (A test is a small program that checks another program does what it should.)
- Is the formatting consistent?
- Are there obvious type mistakes, like passing text where a number was expected?

If every answer is yes, the pipeline goes **green** and the change is safe to merge. If any answer is no, it goes **red** and the change is blocked.

Green means *go*. Red means *someone has to stop what they're doing and deal with this*.

### What goes wrong

Red pipelines happen constantly, and most of them are unglamorous:

- A library the project depends on released a new version that changed how something works.
- Someone renamed a function but missed one place that called it.
- A formatting rule was violated by two spaces.
- A test fails one run in twenty for no clear reason. These are called **flaky tests**, and they are maddening.

None of these are interesting problems. All of them stop the team. Someone has to notice the red, read the logs, figure out the cause, write the fix, and check that the fix didn't break something else. That round trip can take minutes or it can eat an afternoon, and it usually lands on whoever is least busy rather than whoever knows the code best.

Mender is built to take that entire round trip.

## An analogy

Imagine a warning light comes on in your car.

**A notification app** tells you the light is on. Helpful, but you knew.

**A diagnostic scanner** reads the error code and tells you it is probably the oxygen sensor. Better — but "probably" is doing a lot of work, and you still have to do everything.

**A good mechanic** does something different. They put the car on a lift and reproduce the problem so they know it is real and not a fluke. They find the actual cause. They fix it. Then — and this is the part that matters — they take the car out for a test drive to confirm the light stays off and nothing else started rattling. Finally they hand you a receipt showing what was wrong, what they did, and proof that it works now.

And a mechanic worth trusting will sometimes say: *"I couldn't reproduce it, and I'm not going to replace parts on a guess. Here's what I found. Bring it back when it happens again."*

Mender is designed to be the mechanic, including that last part.

| The mechanic | Mender |
| --- | --- |
| Warning light comes on | CI pipeline goes red |
| Get the car on the lift, make the noise happen again | Reproduce the failure in an isolated **sandbox** |
| Find the loose bolt | Diagnose the root cause |
| Tighten it | Write a minimal patch |
| Test drive — light off, nothing new rattling | Failing test passes, full suite still green |
| Hand over the receipt | Open a PR with diagnosis, patch, test, and before/after logs |
| "I won't guess. Here's what I found." | Open an issue with the diagnosis instead of a PR |

## What makes Mender different

Tools that touch this problem already exist. They stop at different places.

| Tool | What it does when CI breaks |
| --- | --- |
| A linter | Names the rule you broke. You fix it. |
| Dependabot | Opens a PR bumping a dependency. If the bump breaks the tests, that is now your problem. |
| A CI notification bot | Posts "build failed" into a chat channel. |
| An AI coding assistant | Suggests a fix in your editor, while you are sitting there. You judge whether it is right. |
| **Mender** | Reproduces the failure, fixes it, writes a test that proves the fix, confirms nothing else broke, and opens a PR containing the evidence. If it cannot prove the fix, it opens an issue with its diagnosis instead. |

Every row above Mender ends at **a suggestion delivered to a human who is already present and paying attention**.

Mender is built to close the loop when nobody is watching — and, just as importantly, to refuse to act when it is not sure.

## The hard part is not the fixing

This is the thing that is easy to miss.

Connecting an AI model to an error message and getting a plausible-looking fix out the other end is not difficult. Anyone can build that in an afternoon.

The engineering is in the two steps around it:

**Reproduction.** Before fixing anything, Mender rebuilds the exact broken state in a clean, isolated environment and confirms the failure actually happens. If it cannot make the failure happen again, the test is probably flaky — and a flaky test needs to be reported and quarantined, never "fixed."

**Proof.** After patching, Mender has to demonstrate three separate things:

1. The test that was failing now passes.
2. The new regression test fails *without* the patch and passes *with* it — proving the test genuinely catches the bug.
3. The rest of the test suite is no worse than before.

If any of those three fail, there is no pull request. Mender writes up what it found and hands it to a human.

A system that knows when to stop is worth more than one with a higher raw fix rate. Read [safety-and-limits.md](safety-and-limits.md) for how that is enforced — it is enforced in code, not politely requested in a prompt.

## What Mender will not do

Being clear about the boundaries is part of being trustworthy.

- **It will not fix logic bugs.** Subtle bugs in business logic are deliberately out of scope for now. An agent that is confidently wrong about a subtle bug destroys trust faster than one that fixes nothing.
- **It will not merge its own work.** Every change goes through a pull request that a human approves.
- **It will not weaken a test to make CI pass.** Deleting a failing test turns the pipeline green while making the software worse. This is the single most dangerous thing an agent like this could do, so it is blocked structurally.
- **It will not touch CI configuration, workflow files, secrets, or database migrations.** Those are the places where a mistake is hardest to undo — and the place where an agent could disable its own safety checks.
- **It will not guess.** Low confidence produces an issue, not a pull request.

## Where to go next

- **[How it works](how-it-works.md)** — the seven steps of the loop, walked through with a real example
- **[Safety and limits](safety-and-limits.md)** — the guardrails, and why each one exists
- **[Glossary](glossary.md)** — every technical term, defined plainly
- **[FAQ](faq.md)** — honest answers, including to the awkward questions
- **[TODO](../TODO.md)** — the build plan, phase by phase

> **Status: early development.** The loop and the safety model are settled. The implementation is in progress. Nothing is usable yet.
