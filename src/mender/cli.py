"""Command-line entry point for Mender.

Each command is one stage of the loop, plus ``repair`` which runs all of them.
Being able to stop after ``classify`` or ``reproduce`` matters: those are the
stages where Mender decides whether to act at all, and they should be
inspectable on their own.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from mender import __version__
from mender.classify import classify
from mender.config import ConfigError, MenderConfig, find_config, load_config
from mender.diagnose.agent import DiagnosisAgent
from mender.diagnose.heuristic import HeuristicAgent
from mender.evals import run_corpus
from mender.models import FailedRun
from mender.repair import Repairer, command_for
from mender.report import Outcome
from mender.sandbox import DockerRunner, LocalRunner, Runner, available, reproduce
from mender.ship.publish import DryRunPublisher, GitHubPublisher, Publisher

app = typer.Typer(
    name="mender",
    help="CI that fixes itself, and proves the fix.",
    no_args_is_help=True,
    add_completion=False,
)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to mender.yaml. Searched upward if omitted."),
]
WorkspaceOption = Annotated[
    Path,
    typer.Option("--workspace", "-w", help="The repository checkout to work against."),
]


class RunnerChoice(StrEnum):
    """Which sandbox backend to execute in."""

    AUTO = "auto"
    DOCKER = "docker"
    LOCAL = "local"


class AgentChoice(StrEnum):
    """Which diagnosis agent to use."""

    HEURISTIC = "heuristic"
    ANTHROPIC = "anthropic"


class PublishChoice(StrEnum):
    """Where the evidence package goes."""

    DRY_RUN = "dry-run"
    GITHUB = "github"


@app.command()
def version() -> None:
    """Print the installed Mender version."""
    typer.echo(f"mender {__version__}")


@app.command()
def validate(config: ConfigOption = None) -> None:
    """Validate a mender.yaml file and summarise the resolved configuration."""
    path, resolved = _load(config)

    blast = f"{resolved.policy.max_files_changed} files / {resolved.policy.max_lines_changed} lines"
    typer.secho(f"{path} is valid.", fg=typer.colors.GREEN)
    typer.echo(f"  language       {resolved.language}")
    typer.echo(f"  test command   {resolved.test_command}")
    typer.echo(f"  sandbox        {resolved.sandbox.image} (network={resolved.sandbox.network})")
    typer.echo(f"  blast radius   {blast}")
    typer.echo(f"  never touch    {len(resolved.policy.never_touch)} protected globs")
    typer.echo(f"  confidence     >= {resolved.diagnose.confidence_threshold}")


@app.command(name="classify")
def classify_logs(
    logs: Annotated[Path, typer.Argument(help="A file containing the failing CI output.")],
    config: ConfigOption = None,
) -> None:
    """Classify a failure from its logs, without running anything."""
    _, resolved = _load(config)
    text = _read(logs)
    result = classify(text)

    colour = typer.colors.GREEN if result.is_repairable else typer.colors.YELLOW
    typer.secho(f"{result.failure_class} (confidence {result.confidence})", fg=colour)
    typer.echo(f"  support        {result.support}")
    typer.echo(f"  matched rule   {result.rule or '(none)'}")
    typer.echo(f"  evidence       {result.evidence}")
    if result.competing_classes:
        typer.echo(f"  also matched   {', '.join(result.competing_classes)}")
    if result.failing_tests:
        typer.echo(f"  failing tests  {', '.join(result.failing_tests)}")
    typer.echo(f"  would run      {command_for(result, resolved)}")

    if result.confidence < resolved.diagnose.confidence_threshold:
        typer.secho(
            f"  Below the configured threshold "
            f"({resolved.diagnose.confidence_threshold}) — Mender would stop here.",
            fg=typer.colors.YELLOW,
        )


@app.command(name="reproduce")
def reproduce_failure(
    logs: Annotated[Path, typer.Argument(help="A file containing the failing CI output.")],
    workspace: WorkspaceOption = Path(),
    config: ConfigOption = None,
    runner: Annotated[
        RunnerChoice, typer.Option("--runner", help="Sandbox backend.")
    ] = RunnerChoice.AUTO,
) -> None:
    """Reproduce a failure in a sandbox and report whether it is real or flaky."""
    _, resolved = _load(config)
    classification = classify(_read(logs))
    backend = _build_runner(runner, resolved)
    command = command_for(classification, resolved)

    typer.echo(f"Running `{command}` in the {backend.name} sandbox…")
    result = reproduce(backend, resolved, workspace, command=command)

    colour = typer.colors.GREEN if result.reproduced else typer.colors.YELLOW
    typer.secho(result.summary, fg=colour)
    typer.echo(f"  attempts       {result.attempts}")
    typer.echo(f"  failure rate   {result.failure_rate:.0%}")
    if not result.reproduced:
        raise typer.Exit(code=2)


@app.command()
def repair(
    logs: Annotated[Path, typer.Argument(help="A file containing the failing CI output.")],
    workspace: WorkspaceOption = Path(),
    config: ConfigOption = None,
    commit: Annotated[str, typer.Option("--commit", help="The failing commit SHA.")] = "HEAD",
    repository: Annotated[
        str, typer.Option("--repository", help="owner/name of the repository.")
    ] = "local/workspace",
    last_green: Annotated[
        str | None,
        typer.Option("--last-green", help="Last commit whose pipeline passed."),
    ] = None,
    runner: Annotated[
        RunnerChoice, typer.Option("--runner", help="Sandbox backend.")
    ] = RunnerChoice.AUTO,
    agent: Annotated[
        AgentChoice, typer.Option("--agent", help="Diagnosis agent.")
    ] = AgentChoice.HEURISTIC,
    publish: Annotated[
        PublishChoice,
        typer.Option("--publish", help="Where the evidence package goes."),
    ] = PublishChoice.DRY_RUN,
    output: Annotated[
        Path, typer.Option("--output", help="Directory for dry-run evidence packages.")
    ] = Path("mender-out"),
) -> None:
    """Run the full loop: classify, reproduce, diagnose, patch, prove, ship."""
    _, resolved = _load(config)
    repairer = Repairer(
        resolved,
        runner=_build_runner(runner, resolved),
        agent=_build_agent(agent),
        publisher=_build_publisher(publish, output),
    )
    run = FailedRun(
        repository=repository,
        commit=commit,
        job="cli",
        logs=_read(logs),
        last_green_commit=last_green,
    )

    report = repairer.repair(run, workspace)

    for step in report.trace:
        typer.echo(f"  {step}")
    colour = typer.colors.GREEN if report.shipped else typer.colors.YELLOW
    typer.secho(f"\n{report.headline}", fg=colour)
    if report.url:
        typer.echo(f"Evidence: {report.url}")
    if report.outcome is Outcome.ERROR:
        raise typer.Exit(code=1)


@app.command()
def watch(
    secret: Annotated[
        str,
        typer.Option(
            "--secret",
            envvar="MENDER_WEBHOOK_SECRET",
            help="Shared webhook secret. Deliveries without a matching signature are rejected.",
        ),
    ],
    inbox: Annotated[
        Path, typer.Option("--inbox", help="Directory failed runs are recorded in.")
    ] = Path("mender-inbox"),
    host: Annotated[str, typer.Option("--host", help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to bind.")] = 8000,
) -> None:
    """Receive CI webhooks and record failed runs for the repair loop."""
    from mender.watch.server import build_server

    server = build_server(secret=secret, inbox=inbox, host=host, port=port)
    typer.secho(f"Listening on http://{host}:{port}/ — recording to {inbox}", fg=typer.colors.GREEN)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        typer.echo("\nStopped.")
    finally:
        server.server_close()


@app.command(name="eval")
def run_evals(
    corpus: Annotated[Path, typer.Option("--corpus", help="The corpus root.")] = Path(
        "evals/corpus"
    ),
    agent: Annotated[
        AgentChoice, typer.Option("--agent", help="Diagnosis agent.")
    ] = AgentChoice.HEURISTIC,
) -> None:
    """Run the historical failure corpus and publish the numbers, flattering or not."""
    if not corpus.is_dir():
        typer.secho(f"No corpus at {corpus}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    results = run_corpus(corpus, agent=_build_agent(agent))
    for result in results.results:
        mark = "✅" if result.matched else "❌"
        typer.echo(
            f"{mark} {result.name:<24} expected {result.expected:<10} "
            f"got {result.actual:<10} ({result.stopped_at})"
        )
        if not result.matched:
            typer.secho(f"     {result.reason}", fg=typer.colors.YELLOW)

    typer.echo("")
    typer.echo(f"  matched          {results.matched}/{results.total}")
    typer.echo(f"  repair rate      {results.repair_rate:.0%}")
    typer.secho(f"  false-fix rate   {results.false_fix_rate:.0%}", fg=typer.colors.CYAN)
    typer.echo(f"  abstention rate  {results.abstention_rate:.0%}")
    typer.echo(f"  mean time        {results.mean_seconds:.1f}s")
    typer.echo(f"  total cost       ${results.total_cost_usd:.4f}")

    if results.matched != results.total:
        raise typer.Exit(code=1)


# --- Wiring ------------------------------------------------------------------


def _load(config: Path | None) -> tuple[Path, MenderConfig]:
    """Find and load the configuration, or exit with a readable message."""
    try:
        path = config if config is not None else find_config()
        return path, load_config(path)
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def _read(path: Path) -> str:
    """Read a log file, or exit with a readable message."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        typer.secho(f"Could not read {path}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def _build_runner(choice: RunnerChoice, config: MenderConfig) -> Runner:
    """Pick a sandbox backend, warning loudly when isolation is given up."""
    if choice is RunnerChoice.DOCKER:
        return DockerRunner(config.sandbox)
    if choice is RunnerChoice.LOCAL:
        _warn_local()
        return LocalRunner()
    if available():
        return DockerRunner(config.sandbox)
    typer.secho(
        "No Docker daemon found; falling back to the local runner.",
        fg=typer.colors.YELLOW,
    )
    _warn_local()
    return LocalRunner()


def _warn_local() -> None:
    """State plainly what the local runner gives up."""
    typer.secho(
        "The local runner has no container, no network isolation, and no resource "
        "caps. Only point it at code you would run yourself.",
        fg=typer.colors.YELLOW,
    )


def _build_agent(choice: AgentChoice) -> DiagnosisAgent:
    """Construct the requested diagnosis agent."""
    if choice is AgentChoice.ANTHROPIC:
        from mender.diagnose.anthropic_agent import AnthropicAgent

        return AnthropicAgent()
    return HeuristicAgent()


def _build_publisher(choice: PublishChoice, output: Path) -> Publisher:
    """Construct the requested publisher."""
    if choice is PublishChoice.GITHUB:
        return GitHubPublisher()
    return DryRunPublisher(output)
