"""Offline hit@3 evaluation for labelled referee states and a saved rule index."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .index import DEFAULT_INDEX_DIR
from .retriever import RuleRetriever
from .validation import DEFAULT_CASES, load_cases, state_from_case

DEFAULT_GOLD = Path(__file__).with_name("retrieval_gold.jsonl")


@dataclass(frozen=True)
class RetrievalGold:
    case_id: str
    gold_rule_ids: tuple[str, ...]


def load_gold(path: str | Path = DEFAULT_GOLD) -> list[RetrievalGold]:
    """Read independently labelled relevant clauses with file/line errors."""
    labels: list[RetrievalGold] = []
    seen: set[str] = set()
    source = Path(path)
    with source.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict) or set(item) != {"case_id", "gold_rule_ids"}:
                    raise ValueError("expected case_id and gold_rule_ids")
                case_id = item["case_id"]
                ids = item["gold_rule_ids"]
                if not isinstance(case_id, str) or not case_id or case_id in seen:
                    raise ValueError("case_id must be unique and non-empty")
                if (
                    not isinstance(ids, list)
                    or not ids
                    or any(not isinstance(rule_id, str) or not rule_id for rule_id in ids)
                    or len(set(ids)) != len(ids)
                ):
                    raise ValueError("gold_rule_ids must be unique, non-empty strings")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{source}:{line_number}: {exc}") from exc
            seen.add(case_id)
            labels.append(RetrievalGold(case_id, tuple(ids)))
    if not labels:
        raise ValueError(f"{source}: no retrieval labels")
    return labels


def evaluate_retrieval(
    retriever: RuleRetriever,
    cases: list[dict[str, Any]],
    labels: list[RetrievalGold],
) -> dict[str, Any]:
    """Measure whether any manually relevant clause appears in the top three.

    Only cases with an explicit gold clause enter the denominator. A gold
    category missing from the filter is reported separately from a ranking miss.
    """
    by_id = {case["id"]: case for case in cases}
    indexed = {chunk["id"]: chunk["category"] for chunk in retriever.chunks}
    if len(by_id) != len(cases):
        raise ValueError("Validation case IDs must be unique")
    if len({label.case_id for label in labels}) != len(labels):
        raise ValueError("Retrieval label case IDs must be unique")
    if not labels:
        raise ValueError("At least one retrieval label is required")

    rows: list[dict[str, Any]] = []
    by_call_type: dict[str, dict[str, int]] = {}
    hits = eligible = 0
    for label in labels:
        case = by_id.get(label.case_id)
        if case is None:
            raise ValueError(f"Unknown validation case: {label.case_id}")
        missing = set(label.gold_rule_ids) - indexed.keys()
        if missing:
            raise ValueError(
                f"Gold rules absent from index for {label.case_id}: {', '.join(sorted(missing))}"
            )
        state = state_from_case(case)
        result = retriever.retrieve(state, top_k=3)
        gold = set(label.gold_rule_ids)
        rank = next((i for i, rule_id in enumerate(result.chunk_ids, 1) if rule_id in gold), None)
        category_eligible = any(indexed[rule_id] in result.categories for rule_id in gold)
        hit = rank is not None
        hits += hit
        eligible += category_eligible
        expected = case["expected"]
        call_type = (
            expected.get("foul_type")
            or expected.get("violation_type")
            or expected.get("call", "NONE")
        )
        counts = by_call_type.setdefault(call_type, {"hits": 0, "total": 0})
        counts["hits"] += hit
        counts["total"] += 1
        rows.append({
            "case_id": label.case_id,
            "call_type": call_type,
            "gold_rule_ids": list(label.gold_rule_ids),
            "retrieved_rule_ids": result.chunk_ids,
            "selected_categories": list(result.categories),
            "category_eligible": category_eligible,
            "first_hit_rank": rank,
            "hit_at_3": hit,
            "miss_reason": None if hit else "ranking" if category_eligible else "category_filter",
        })

    total = len(labels)
    return {
        "index_backend": retriever.backend,
        "index_model": retriever.model_name,
        "cases_total": len(cases),
        "labelled_cases": total,
        "unlabelled_cases": len(cases) - total,
        "hit_at_3": {"hits": hits, "total": total, "rate": hits / total},
        "category_filter_recall": {
            "eligible": eligible, "total": total, "rate": eligible / total,
        },
        "by_call_type": {
            kind: {**counts, "rate": counts["hits"] / counts["total"]}
            for kind, counts in sorted(by_call_type.items())
        },
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate WS5 rule retrieval hit@3 locally")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    args = parser.parse_args(argv)
    try:
        retriever = RuleRetriever(args.index_dir)
        report = evaluate_retrieval(
            retriever, load_cases(args.cases), load_gold(args.gold),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
