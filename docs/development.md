# Development setup

How to get Mender running locally and make a change with confidence.

New to the project itself? Read [what-is-mender.md](what-is-mender.md) first — this page assumes you know what Mender is trying to do.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [The quality gate](#the-quality-gate)
- [Project layout](#project-layout)
- [Making a change](#making-a-change)
- [Where to contribute](#where-to-contribute)

## Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | 0.5+ | Dependency and Python version management |
| Python | 3.12+ | Running the project (uv installs it if missing) |
| Docker | 24+ | The reproduction sandbox |
| Git | 2.40+ | Everything |

Only `uv` and Git are needed to run the test suite: it uses the local runner
throughout, and the Docker backend is tested by inspecting the arguments it
builds rather than by starting a container. Docker is needed to actually
reproduce a failure under isolation.

## Setup

```bash
git clone https://github.com/dileepadev/mender.git
cd mender
uv sync --dev
```

That is the whole setup. `uv` creates the virtual environment, installs the correct Python, resolves every dependency from `uv.lock`, and installs Mender in editable mode.

Confirm it worked:

```bash
uv run pytest
```

A green run means you are ready.

## The quality gate

Four commands, and CI runs exactly these. Run them before opening a pull request.

```bash
uv run ruff check .          # lint
uv run ruff format .         # format (use --check in CI)
uv run mypy                  # strict type checking
uv run pytest                # tests with coverage
uv run mender eval           # the corpus, end to end
```

All five in one line:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run mender eval
```

`mender eval` is the closest thing here to an integration test: five real
repositories, five real reproductions, five real outcomes. A case that stops
reaching its expected outcome fails the build. See
[evals/README.md](../evals/README.md).

A few things worth knowing about the configuration:

- **mypy runs in strict mode.** Every function needs annotations. This is deliberate — the project handles patches and policy decisions where a type confusion is a safety bug, not a style issue.
- **Ruff enforces docstrings** (Google convention) on public modules, classes, and functions. Test functions are exempt.
- **Warnings are errors** in pytest. A new `DeprecationWarning` fails the suite rather than accumulating quietly.
- **Line length is 100**, enforced by the formatter.
- **`evals/corpus/` is excluded from linting.** The fixtures there are deliberately broken; one of them exists precisely because it has an unused import.

Markdown is linted too, with `MD013` (line length) disabled — see `.markdownlint.json`:

```bash
npx markdownlint-cli2
```

## Project layout

```text
mender/
├── mender.yaml             # Mender's configuration for this repository
├── pyproject.toml          # dependencies, ruff, mypy, and pytest config
├── src/mender/
│   ├── cli.py              # one command per stage, plus `repair`
│   ├── config.py           # mender.yaml schema and the built-in protections
│   ├── models.py           # the values each stage hands the next
│   ├── repair.py           # the loop, and every exit from it
│   ├── report.py           # the record of one trip through the loop
│   ├── evals.py            # the corpus harness
│   ├── watch/              # CI webhook and run ingestion
│   ├── classify/           # log parsers → failure class
│   ├── sandbox/            # containerised reproduction
│   ├── policy/             # blast radius + the test-weakening detector
│   ├── diagnose/           # provider-agnostic agent layer
│   ├── patch/              # applying and reverting under policy
│   ├── verify/             # the proof step
│   └── ship/               # PR authoring with evidence
├── policies/               # the default policy shipped with Mender
├── evals/corpus/           # broken repositories with known correct outcomes
├── tests/                  # mirrors src/mender/
└── docs/                   # the documentation you are reading
```

Two dependency rules hold the safety model up, and both are worth knowing before
you move code around:

- **Nothing executes outside a `Runner`.** The proof step holds a runner, not a
  subprocess, so it cannot accidentally run a repository's test command outside
  a sandbox.
- **`policy/` does not import `diagnose/`, and never sees a log.** That is what
  makes the guardrails independent of whatever the agent was persuaded to
  attempt.

Where a stage's implementation is complete and what is still missing is tracked
phase by phase in [TODO.md](../TODO.md).

## Making a change

1. **Branch** using the [branch naming guidelines](../BRANCH_NAMING_GUIDELINES.md) — `feat/x`, `fix/x`, `docs/x`, and so on. Never commit to `main` or `dev` directly.
2. **Write the test first** where practical. This project's entire thesis is that a fix without a test proving it is not a fix.
3. **Run the quality gate.** All four commands.
4. **Commit** using the [commit message guidelines](../COMMIT_MESSAGE_GUIDELINES.md) — `feat(sandbox): Add container teardown (refs #12)`.
5. **Open a pull request** following the [pull request guidelines](../PULL_REQUEST_GUIDELINES.md).

### A note on testing safety code

Anything touching the policy engine, the test-weakening detector, or the sandbox limits needs **adversarial tests**, not just happy-path ones. Write the patch that tries to cheat, then assert it is rejected.

`tests/policy/test_weakening_adversarial.py` is the canonical example: every
patch in it turns a red pipeline green while making the software worse, and all
of them must be rejected. New cheats belong there the day somebody thinks of one
— the point of the suite is that it grows faster than the ways around it.

`tests/test_config.py` shows the same idea at the configuration layer: several
tests exist purely to prove a repository cannot remove a built-in never-touch
glob through its own configuration.

## Where to contribute

The highest-value contributions right now are **eval cases** — small,
deliberately broken repositories that reproduce one specific failure class,
paired with the outcome Mender should reach. Everything is measured against
them, so the corpus is the bottleneck. Cases where the right answer is to
decline are as valuable as cases where the right answer is a fix.

See [evals/README.md](../evals/README.md) for the case format, and
[TODO.md](../TODO.md) for what is still missing elsewhere.

For anything larger, open an issue first so the approach can be agreed before you spend time on it.
