# FAQ

Honest answers, including to the awkward questions.

## Table of Contents

- [About the idea](#about-the-idea)
- [About trust](#about-trust)
- [Practical questions](#practical-questions)
- [About the project](#about-the-project)

## About the idea

### Isn't this just "AI writes code"?

The code-writing is the easy part, and it is not what makes this hard.

Connecting a model to a stack trace and getting a plausible-looking patch takes an afternoon. What takes engineering is everything around it: rebuilding the broken state exactly, confirming the failure is real rather than flaky, proving the patch fixes it, proving the new test actually catches the bug, and confirming nothing else broke — then declining to open a pull request when any of that fails.

Mender is a verification system that happens to contain a code generator, not the other way around.

### How is this different from an AI assistant in my editor?

An editor assistant helps a developer who is already sitting there, already aware something broke, already deciding what to do about it. It ends at a suggestion, and a human judges it immediately.

Mender is built for when nobody is watching. Nobody is present to catch a bad suggestion, so a suggestion is not good enough — it has to be a proof, or nothing at all.

### How is this different from Dependabot or Renovate?

Those tools bump dependency versions on a schedule. That is genuinely useful, and it is a different job.

The difference shows up when the bump breaks something. Dependabot opens the PR, the tests go red, and the problem is now yours. Mender starts where that ends: it reproduces the break, works out what changed in the new version, patches the calling code, and proves the suite is green again.

### Does this replace developers?

No, and the design pushes against that reading.

Mender targets a narrow band of tedious failures — formatting violations, type errors, incomplete renames, dependency drift. The failures where the right answer is unambiguous and the only cost is a human's interrupted afternoon.

Logic bugs, design decisions, and anything requiring judgment about what the code *should* do are explicitly out of scope. Every change still goes through human review. Nothing merges without approval.

The goal is to stop pulling engineers off real work to fix a missing import.

## About trust

### What if it writes a bad fix?

This is the right question, and it is the one the whole design is organised around.

Three things stand in the way:

1. **Proof before shipping.** A patch only becomes a pull request if the failing test passes, the new regression test genuinely catches the bug (fails without the patch, passes with it), and the full suite shows no new failures.
2. **Policy in code.** Hard limits on files touched, lines changed, and paths allowed — plus a dedicated detector that rejects any patch weakening a test. Enforced before a pull request exists, not requested in a prompt.
3. **Human approval.** Mender never merges. Every change is reviewed with the full evidence attached.

And when Mender cannot satisfy those, it opens an issue with its diagnosis instead. See [safety-and-limits.md](safety-and-limits.md).

### What stops it from just deleting the failing test?

A patch inspector that runs on every generated diff and rejects deletions, `skip`/`xfail` markers, relaxed assertions, widened tolerances, and lowered coverage thresholds.

It compares the **structure** of the code, not the text, so cosmetic tricks do not get past it. There is also an adversarial suite of deliberately cheating patches that must all be rejected, running in Mender's own CI — so weakening the detector turns Mender's pipeline red.

This is covered in detail in [safety-and-limits.md](safety-and-limits.md).

### What if a fix passes CI but is still wrong?

That is called a **false fix**, and it is the most important risk in the entire project.

It cannot be eliminated. Tests are an incomplete description of correct behaviour, so a patch can satisfy every test and still be wrong.

What Mender does instead is measure it honestly. False-fix rate will be published alongside every other metric, including when the number is unflattering. It is the figure that makes the rest believable — a repair rate quoted without a false-fix rate next to it means very little.

### Why publish the unflattering numbers?

Because a tool like this is worth nothing without trust, and trust is not built by publishing only the good results.

Anyone can report a high fix rate. Reporting how often those fixes were wrong is the part that lets someone decide whether to actually run this on their repository.

### Isn't an autonomous agent editing code just a bad idea?

It would be, without limits. That is why the limits came first.

The specific things that make it defensible: the agent cannot touch CI configuration or workflow files, cannot weaken tests, cannot exceed a declared blast radius, cannot merge anything, runs all code in a network-isolated disposable sandbox, and stops entirely when confidence is low.

An agent with no boundaries editing arbitrary code is a bad idea. Mender is an attempt to work out what the boundaries have to be.

## Practical questions

### Can I use it now?

No. Mender is in early development. The loop and the safety model are settled; the implementation is in progress. Nothing is usable yet.

Follow the repository, or check [TODO.md](../TODO.md) for current progress.

### What languages will it support?

Python first, deliberately and exclusively.

One language proven end to end is worth more than four half-supported ones. JS/TS is the intended second, added through a language adapter interface — which will also prove the abstraction is real rather than assumed.

### Why Python first?

The tooling is unusually well-suited to this. `ruff` and `mypy` produce machine-readable output, `pytest` has a stable and parseable failure format, and Python tracebacks are consistent enough to classify reliably. Good signal makes the first slice tractable.

### Which CI providers?

GitHub Actions first, for the same reason. GitLab CI is the intended second, behind a provider interface.

### What does it cost to run?

Unknown until the benchmark exists — cost per repair is one of the published metrics.

There will be a hard cost ceiling per repair attempt, configurable, so a difficult failure cannot run up an open-ended bill.

### What can it see in my repository?

Only what it needs, and only in a disposable sandbox: the code at the failing commit, the CI logs, and the diff since the last green run.

Secrets are on the never-touch list — never read, never written. The sandbox has no network access by default. Nothing survives the run.

### Will it work on private repositories?

Yes, that is the intended primary use. Public repositories introduce an extra concern — logs from untrusted contributors are attacker-controlled input — which is handled by treating all log content as data and enforcing the guardrails structurally rather than through prompts.

### What happens with flaky tests?

Mender detects them and refuses to edit them.

If a failure will not reproduce, Mender re-runs it several times, measures how often it actually fails, and reports it for quarantine. It does not "fix" a flaky test, because there is usually nothing in the test to fix — and editing it to stop failing would be hiding the problem rather than solving it.

### Can it fix logic bugs?

Not for now, deliberately.

Subtle bugs in business logic are exactly where an agent is most likely to be confidently wrong, and confident wrongness is the fastest way to lose trust in an autonomous tool. The excluded categories are recorded in [TODO.md](../TODO.md) so the scope stays honest.

## About the project

### How will I know if it actually works?

Mender will be measured against a curated corpus of real historical CI failures with known human fixes, and the results published: repair rate by failure class, false-fix rate, PR acceptance rate, time from failure to PR, cost per repair, and abstention rate.

Anecdotes are not evidence. The benchmark is [Phase 10](../TODO.md) of the plan.

### Why is verification treated as the hard part?

Because it is the only thing separating this from every other tool that suggests fixes.

The industry has plenty of systems that produce a plausible patch. What is missing is a system that can demonstrate the patch is correct, and reliably decline when it cannot. That demonstration — reproduce, patch, prove the regression test catches the bug, prove nothing else broke — is where the actual difficulty lives.

### Can I contribute?

Yes. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the workflow, and [TODO.md](../TODO.md) for what is planned and in what order.

The project is in early phases, so the highest-value contributions right now are test fixtures — small, deliberately broken repositories that reproduce a specific failure class. Everything downstream is developed and measured against those.

### Where do I start reading?

- New to CI entirely → [what-is-mender.md](what-is-mender.md)
- Want the mechanics → [how-it-works.md](how-it-works.md)
- Sceptical about safety → [safety-and-limits.md](safety-and-limits.md)
- Lost in the jargon → [glossary.md](glossary.md)
- Want to help build it → [TODO.md](../TODO.md)
