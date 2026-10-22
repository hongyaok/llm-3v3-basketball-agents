"""Run a game prefix with local embeddings and fake or live players."""

import argparse
import asyncio
import json
from pathlib import Path

from bball3x3.config import load_llm_config
from bball3x3.llm import FakeLLM, LegalXMLPolicy, OpenRouterClient
from bball3x3.memory.embeddings import LocalEmbedder
from bball3x3.runner.llm_game import run_llm_game


async def main(args):
    path = Path(args.output)
    checkpoint = path.with_suffix(".ckpt.json")

    if path.exists() or checkpoint.exists():
        raise FileExistsError(
            "Output or checkpoint already exists. Choose a new output path."
        )

    cfg = load_llm_config()
    if cfg.embeddings.backend != "local":
        raise ValueError("This launcher supports only local embeddings")

    embedder = LocalEmbedder(cfg.embeddings.model)

    # Load the model before beginning the game.
    embedder("Basketball coordination")

    backend = (
        OpenRouterClient(cfg)
        if args.live
        else FakeLLM(LegalXMLPolicy())
    )

    path.parent.mkdir(parents=True, exist_ok=True)

    result = await run_llm_game(
        llm=backend,
        path=path,
        seed=args.seed,
        llm_config=cfg,
        embedder=embedder,
        similarity_threshold=args.threshold,
        max_events=args.max_events,
    )
    print(json.dumps(result, indent=2))
    print("Player backend:", "live OpenRouter" if args.live else "fake")
    print("Embedding model:", cfg.embeddings.model)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--max-events", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    if args.max_events < 1:
        parser.error("--max-events must be positive")
    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold must be between 0 and 1")

    asyncio.run(main(args))