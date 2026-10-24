"""Run one experiment config: every seed played twice with swapped first possession."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bball3x3.config import ExperimentConfig, LLMConfig
from bball3x3.llm.base import LLMBackend
from bball3x3.llm.budget import BudgetTracker
from bball3x3.runner.llm_game import run_llm_game

MANIFEST = "manifest.json"


@dataclass(frozen=True)
class GameSpec:
    game_id: str
    seed: int
    first_possession: str | None
    path: Path


def plan_games(exp: ExperimentConfig, out_dir: Path) -> list[GameSpec]:
    sides: tuple[str | None, ...] = ("A", "B") if exp.swap_first_possession else (None,)
    specs = []
    for seed in exp.seeds:
        for side in sides:
            game_id = f"{exp.experiment_id}_s{seed}_{side or 'coin'}"
            specs.append(GameSpec(game_id, seed, side, out_dir / f"{game_id}.jsonl"))
    return specs


# finished games end with game_end and leave no checkpoint behind
def is_complete(path: Path) -> bool:
    if not path.exists() or path.with_suffix(".ckpt.json").exists():
        return False
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return bool(lines) and json.loads(lines[-1]).get("record_type") == "game_end"


def _write_manifest(out_dir: Path, exp: ExperimentConfig, games: dict, spent: float) -> None:
    payload = {"experiment_id": exp.experiment_id, "spent_usd": round(spent, 6), "games": games}
    (out_dir / MANIFEST).write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def run_experiment(
    exp: ExperimentConfig,
    *,
    llm: LLMBackend,
    llm_config: LLMConfig,
    out_dir: str | Path,
    budget: BudgetTracker | None = None,
    referee_backend_factory: Callable[[], LLMBackend] | None = None,
    **game_options: Any,
) -> dict[str, Any]:
    """Play every planned game, skipping finished ones and resuming checkpoints."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / MANIFEST
    previous = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    games: dict[str, dict[str, Any]] = previous.get("games", {})
    # spend from earlier interrupted runs still counts toward the cap
    carried = float(previous.get("spent_usd", 0.0))
    if budget is not None:
        budget.spent_usd += carried

    coordination = {"A": exp.matchup.home.coordination, "B": exp.matchup.away.coordination}
    conditions = {"A": exp.matchup.home.label, "B": exp.matchup.away.label}
    semaphore = asyncio.Semaphore(exp.max_concurrent_games)

    def spent() -> float:
        return budget.spent_usd if budget is not None else carried

    async def play(spec: GameSpec) -> None:
        entry = {"seed": spec.seed, "first_possession": spec.first_possession,
                 "path": str(spec.path)}
        if is_complete(spec.path):
            games[spec.game_id] = {**games.get(spec.game_id, entry), "status": "complete"}
            return
        async with semaphore:
            try:
                result = await run_llm_game(
                    llm=llm, path=spec.path, seed=spec.seed, game_id=spec.game_id,
                    experiment_id=exp.experiment_id, replicate_id=f"seed_{spec.seed}",
                    llm_config=llm_config, coordination=coordination,
                    team_conditions=conditions, first_possession=spec.first_possession,
                    resume=spec.path.with_suffix(".ckpt.json").exists(),
                    llm_backend_for_referee=(
                        referee_backend_factory() if referee_backend_factory else None
                    ),
                    **game_options,
                )
            except Exception as exc:
                games[spec.game_id] = {**entry, "status": "failed", "error": repr(exc)[:300]}
                raise
            finally:
                _write_manifest(out, exp, games, spent())
            status = "complete" if result.get("game_complete") else "stopped"
            games[spec.game_id] = {**entry, "status": status, "events": result.get("events"),
                                   "score": result.get("score")}
            _write_manifest(out, exp, games, spent())

    specs = plan_games(exp, out)
    outcomes = await asyncio.gather(*(play(s) for s in specs), return_exceptions=True)
    _write_manifest(out, exp, games, spent())
    errors = [o for o in outcomes if isinstance(o, BaseException)]
    return {
        "experiment_id": exp.experiment_id,
        "planned": [asdict(s) | {"path": str(s.path)} for s in specs],
        "games": games,
        "spent_usd": spent(),
        "errors": [repr(e)[:300] for e in errors],
    }
