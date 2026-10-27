"""Experiment running, game-log analysis and rulebook indexing commands."""

import json
import os
from pathlib import Path

import typer

from .analysis import (
    analyse_experiment,
    build_adaptation_plot_data,
    build_experiment_tables,
    read_experiment_tables,
    read_game_log,
    render_possession_transcript,
    write_adaptation_plots,
    write_experiment_stats,
    write_experiment_tables,
)

app = typer.Typer(no_args_is_help=True, help="Inspect saved 3v3 basketball game logs.")


@app.callback()
def main() -> None:
    """Offline tools for saved games and the local FIBA rulebook."""


@app.command("dashboard")
def dashboard(
    results: Path | None = typer.Option(None, "--results"),
    runs: Path | None = typer.Option(None, "--runs"),
    experiments_root: Path = typer.Option(Path("runs"), "--experiments-root"),
    port: int = typer.Option(8765, "--port", min=1, max=65535),
) -> None:
    """Open a local results dashboard and game replay server (no LLM calls)."""
    from .display.dashboard import serve_dashboard

    try:
        serve_dashboard(results, runs, port, experiments_root)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("build-index")
def build_rule_index(
    pdf: Path = typer.Argument(
        Path("data/rules/fiba-3x3-basketball-rules-full-version.pdf"),
        help="Local FIBA 3x3 rulebook PDF.",
    ),
    output_dir: Path = typer.Option(Path("data/rules"), "--output-dir"),
    backend: str = typer.Option(
        "sentence-transformers", "--backend", help="sentence-transformers or hash",
    ),
    model: str | None = typer.Option(None, "--model"),
    force: bool = typer.Option(False, "--force", help="Replace existing index files."),
) -> None:
    """Extract referee-relevant clauses and write aligned chunks and embeddings."""
    from .referee.index import build_index

    try:
        manifest = build_index(
            pdf, output_dir, backend=backend, model=model, force=force,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(manifest, indent=2, sort_keys=True))


def _load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@app.command("run-experiment")
def run_experiment_command(
    config: Path = typer.Argument(..., exists=True, dir_okay=False,
                                  help="Experiment YAML, e.g. configs/experiments/pilot.yaml."),
    out_root: Path = typer.Option(Path("runs"), "--out", help="Logs go to <out>/<experiment_id>/."),
    max_events: int = typer.Option(2000, "--max-events", min=1),
    memory: str = typer.Option("embedding", "--memory", help="embedding or exact"),
    dry_run: bool = typer.Option(False, "--dry-run", help="List planned games, call no model."),
) -> None:
    """Play every seed twice with swapped first possession, resuming unfinished games."""
    import asyncio

    from .config import load_experiment_config, load_llm_config
    from .runner.experiment import is_complete, plan_games, run_experiment

    exp = load_experiment_config(config)
    out_dir = out_root / exp.experiment_id
    if dry_run:
        for spec in plan_games(exp, out_dir):
            done = "done" if is_complete(spec.path) else "todo"
            typer.echo(f"{done}  {spec.game_id}  seed={spec.seed}  first={spec.first_possession}")
        return
    if memory not in ("embedding", "exact"):
        typer.echo("Error: --memory must be embedding or exact", err=True)
        raise typer.Exit(code=1)

    from .llm.budget import BudgetTracker
    from .llm.client import OpenRouterClient
    from .memory.embeddings import LocalEmbedder

    _load_env()
    llm_cfg = load_llm_config()
    budget = BudgetTracker(llm_cfg.runtime.budget.get("max_usd_per_experiment"))
    embedder = LocalEmbedder(llm_cfg.embeddings.model) if memory == "embedding" else None
    llm_referee = llm_cfg.referee.enabled and llm_cfg.referee.backend == "llm"

    async def go() -> dict:
        client = OpenRouterClient(llm_cfg, budget=budget)
        try:
            return await run_experiment(
                exp, llm=client, llm_config=llm_cfg, out_dir=out_dir, budget=budget,
                # each game's referee runs on its own loop thread, so it gets its own client
                referee_backend_factory=(
                    (lambda: OpenRouterClient(llm_cfg, budget=budget)) if llm_referee else None
                ),
                max_events=max_events, embedder=embedder,
            )
        finally:
            await client.aclose()

    result = asyncio.run(go())
    for game_id, entry in sorted(result["games"].items()):
        typer.echo(f"{entry['status']:9} {game_id}  score={entry.get('score')}")
    typer.echo(f"spent ${result['spent_usd']:.4f}, manifest at {out_dir / 'manifest.json'}")
    if result["errors"]:
        for error in result["errors"]:
            typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1)


@app.command()
def transcript(
    game: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    possession: str = typer.Argument(..., help="Exact possession ID, e.g. p0001."),
) -> None:
    """Print observations, communication, decisions and outcomes for a possession."""
    try:
        rendered = render_possession_transcript(read_game_log(game), possession)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(rendered, nl=False)


@app.command("export")
def export_experiment(
    output_dir: Path = typer.Argument(..., help="New directory for CSV tables and manifest."),
    games: list[Path] = typer.Argument(..., help="One or more saved game JSONL paths."),
    include_incomplete: bool = typer.Option(False, "--include-incomplete"),
    window: int = typer.Option(1, "--window", min=1, max=2),
) -> None:
    """Export game, team, and possession tables from saved logs."""
    try:
        tables = build_experiment_tables(games, include_incomplete=include_incomplete,
                                         window=window)
        write_experiment_tables(tables, output_dir)
    except FileExistsError as exc:
        typer.echo(f"Error: File exists: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Exported {len(tables.games)} games, {len(tables.teams)} teams, "
        f"{len(tables.possessions)} possessions to {output_dir}"
    )


@app.command("stats")
def experiment_stats(
    export_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    output_json: Path = typer.Argument(..., help="New JSON file for the analysis results."),
    baseline: str = typer.Option("A_full", "--baseline"),
    analysis_seed: int = typer.Option(4213, "--analysis-seed"),
    bootstrap_replicates: int = typer.Option(10_000, "--bootstrap-replicates", min=100),
) -> None:
    """Compute seed-paired effects and exploratory possession models from an export."""
    try:
        result = analyse_experiment(read_experiment_tables(export_dir), baseline=baseline,
                                    analysis_seed=analysis_seed,
                                    bootstrap_replicates=bootstrap_replicates)
        write_experiment_stats(result, output_json)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Analysed {len(result['results'])} comparisons to {output_json}")


@app.command("plots")
def adaptation_plots(
    export_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    output_dir: Path = typer.Argument(..., help="New directory for PNG curves and pooled CSV."),
    baseline: str = typer.Option("A_full", "--baseline"),
) -> None:
    """Render PPP, MAUR and CSSR curves from saved experiment tables."""
    try:
        data = build_adaptation_plot_data(read_experiment_tables(export_dir), baseline=baseline)
        write_adaptation_plots(data, output_dir)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Wrote {len(data.manifest['groups']) * 3} plots to {output_dir}")
