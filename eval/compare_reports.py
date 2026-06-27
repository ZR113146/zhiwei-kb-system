# -*- coding: utf-8 -*-
"""Compare two KB evaluation reports."""

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASELINE = os.path.join(ROOT, "eval", "baseline_report.json")
DEFAULT_OUTPUT = os.path.join(ROOT, "eval", "comparison_report.md")

METRICS = [
    "recall_at_5",
    "mrr",
    "ndcg_at_10",
    "clause_hit_rate",
    "no_result_rate",
    "stale_hit_rate",
    "avg_elapsed_ms",
    "errors",
]
LOWER_IS_BETTER = {"no_result_rate", "stale_hit_rate", "avg_elapsed_ms", "errors"}


def load_report(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def metric_value(report, key):
    return report.get("summary", {}).get("overall", {}).get(key)


def row_by_query(report):
    return {row.get("query", f"line:{row.get('line')}"): row for row in report.get("rows", [])}


def compare(base, current):
    metrics = []
    for key in METRICS:
        old = metric_value(base, key)
        new = metric_value(current, key)
        if old is None or new is None:
            delta = None
            verdict = "n/a"
        else:
            delta = round(new - old, 4) if isinstance(new, (int, float)) else None
            if delta == 0:
                verdict = "same"
            elif key in LOWER_IS_BETTER:
                verdict = "better" if delta < 0 else "worse"
            else:
                verdict = "better" if delta > 0 else "worse"
        metrics.append({"metric": key, "baseline": old, "current": new, "delta": delta, "verdict": verdict})

    base_rows = row_by_query(base)
    current_rows = row_by_query(current)
    regressions = []
    improvements = []
    for query, current_row in current_rows.items():
        base_row = base_rows.get(query)
        if not base_row:
            continue
        old_rank = base_row.get("first_rank")
        new_rank = current_row.get("first_rank")
        if old_rank and not new_rank:
            regressions.append({"query": query, "from": old_rank, "to": None, "reason": "lost_hit"})
        elif old_rank and new_rank and new_rank > old_rank:
            regressions.append({"query": query, "from": old_rank, "to": new_rank, "reason": "rank_worse"})
        elif not old_rank and new_rank:
            improvements.append({"query": query, "from": None, "to": new_rank, "reason": "new_hit"})
        elif old_rank and new_rank and new_rank < old_rank:
            improvements.append({"query": query, "from": old_rank, "to": new_rank, "reason": "rank_better"})

    return {"metrics": metrics, "regressions": regressions, "improvements": improvements}


def write_markdown(result, output_path):
    lines = ["# KB Evaluation Comparison", "", "## Metrics", ""]
    for item in result["metrics"]:
        lines.append(f"- {item['metric']}: {item['baseline']} -> {item['current']} delta={item['delta']} {item['verdict']}")
    lines.extend(["", "## Regressions", ""])
    for item in result["regressions"][:80]:
        lines.append(f"- `{item['query']}` {item['from']} -> {item['to']} ({item['reason']})")
    lines.extend(["", "## Improvements", ""])
    for item in result["improvements"][:80]:
        lines.append(f"- `{item['query']}` {item['from']} -> {item['to']} ({item['reason']})")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Compare KB eval reports")
    parser.add_argument("current", help="current eval report json")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    result = compare(load_report(args.baseline), load_report(args.current))
    write_markdown(result, args.output)
    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({"regressions": len(result["regressions"]), "improvements": len(result["improvements"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
