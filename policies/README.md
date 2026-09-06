# Policies

Blast-radius limits, forbidden edits, and approval rules. **The agent proposes; policy disposes.**

## What is here

- [`default.yaml`](default.yaml) — the default policy Mender ships with. A repository overrides it in the `policy:` block of its own `mender.yaml`. `tests/policy/test_default_policy.py` asserts this file and the code defaults cannot drift apart.

The engine that enforces it lives in [`src/mender/policy/`](../src/mender/policy/):

| Module | What it does |
| --- | --- |
| `engine.py` | Evaluates a finished patch and returns an approval or the specific rules it broke |
| `weakening.py` | The test-weakening detector, working on the AST |
| `globs.py` | Path matching where `*` never crosses a directory separator |
| `rules.py` | The rule identifiers every rejection is reported under |

## What is not here, deliberately

The built-in never-touch globs live in code — `BUILTIN_NEVER_TOUCH` in
[`src/mender/config.py`](../src/mender/config.py) — not in this directory. A
policy *file* that could remove them would be a policy file an agent could edit
its way past. A repository may add protections through its `mender.yaml`; it can
never remove them, and `tests/test_config.py` asserts that invariant directly.

`policies/**` is itself on the never-touch list.

## The test-weakening detector

The guardrail the whole project is designed around. It rejects a patch that:

- deletes a test, or a whole test file
- adds a `skip`, `skipif`, or `xfail` marker, or a skip call, or an early return
- removes an assertion from an existing test
- relaxes an assertion — `== 90` becoming `is not None`, say
- widens a numeric tolerance, or lowers an `assertAlmostEqual` precision
- drops cases from a `parametrize` list
- lowers or removes a coverage threshold

It works on the abstract syntax tree, not the text. A regular expression looking
for the word `skip` is trivially avoided; comparing the structure of the
assertions before and after is not.

**Existing assertions may be renamed, not rewritten.** Two assertions are the
same assertion when their trees are identical after every identifier is
normalised away. So finishing an incomplete rename inside a test is allowed, and
changing an expected value, an operator, or a tolerance is not. Mender does not
repair logic bugs, so it never has a legitimate reason to change what a test
expects.

Adding tests, and adding assertions to existing tests, is always allowed.

## The adversarial suite

[`tests/policy/test_weakening_adversarial.py`](../tests/policy/test_weakening_adversarial.py)
is a collection of hand-written patches that deliberately try to cheat, in every
way we can think of. All of them must be rejected, every time, and the suite runs
in CI — so weakening the detector turns Mender's own pipeline red.

New cheats belong there the day somebody thinks of one. The point of the suite is
that it grows faster than the ways around it.

## Why this is code, not prompt text

A model can reason its way around an instruction. It cannot reason its way around
a patch that is rejected before it becomes a pull request. The engine never reads
the logs, so an injection that successfully confuses the agent still has to get a
forbidden patch past code that was never exposed to the text that did the
confusing.

See [docs/safety-and-limits.md](../docs/safety-and-limits.md) for the full reasoning.
