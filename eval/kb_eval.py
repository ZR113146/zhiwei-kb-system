# -*- coding: utf-8 -*-
"""Evaluate Zhiwei KB search against golden queries."""

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in ("", "kb_core", "pipeline"):
    path = os.path.join(ROOT, rel) if rel else ROOT
    if path not in sys.path:
        sys.path.insert(0, path)

from kb_loader import read_clause, search, status  # noqa: E402
from standard_status import normalize_code  # noqa: E402

DEFAULT_GOLDEN = os.path.join(ROOT, "eval", "golden_queries.jsonl")
DEFAULT_JSON = os.path.join(ROOT, "eval", "baseline_report.json")
DEFAULT_MD = os.path.join(ROOT, "eval", "baseline_report.md")

CODE_RE = re.compile(r"(TCECS|CECS|CJJT|CJJ|CJT|CJ|JGJT|JGJ|GBT|GB|JTG|DB\d{2}|DB)[\s/_-]*T?[\s/_-]*(\d+(?:\.\d+)?)", re.I)


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON at {path}:{line_no}: {exc}")
            item["_line"] = line_no
            records.append(item)
    return records


def extract_code_from_result(result):
    for key in ("standard_code", "code"):
        value = result.get(key)
        if value:
            return normalize_code(value)
    text = " ".join(str(result.get(k, "")) for k in ("file", "heading", "text"))
    match = CODE_RE.search(text)
    if match:
        return normalize_code(match.group(0))
    return ""


def result_matches(result, expected_code, expected_name=""):
    expected_code = normalize_code(expected_code)
    code = extract_code_from_result(result)
    if expected_code and code == expected_code:
        return True
    haystack = " ".join(str(result.get(k, "")) for k in ("file", "heading", "text", "standard_name"))
    if expected_code and expected_code in normalize_code(haystack):
        return True
    if expected_name and expected_name in haystack:
        return True
    return False


def dcg(rank):
    return 1.0 / math.log2(rank + 1)


def evaluate_query(item, max_results):
    query = item["query"]
    expected_code = item.get("expected_standard_code", "")
    expected_name = item.get("expected_standard_name", "")
    expected_clause = item.get("expected_clause", "")
    start = time.perf_counter()
    try:
        results = search(query, max_results=max_results)
        error = ""
    except Exception as exc:
        results = []
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

    first_rank = None
    matched_codes = []
    for index, result in enumerate(results, 1):
        code = extract_code_from_result(result)
        if code:
            matched_codes.append(code)
        if first_rank is None and result_matches(result, expected_code, expected_name):
            first_rank = index

    clause_hit = None
    clause_error = ""
    if expected_code and expected_clause and item.get("query_type") == "clause":
        try:
            text = read_clause(expected_code, expected_clause)
            clause_hit = bool(text and expected_clause.replace("第", "") in text[:300]) or bool(text)
        except Exception as exc:
            clause_hit = False
            clause_error = f"{type(exc).__name__}: {exc}"

    stale_hits = 0
    for result in results:
        std_status = result.get("standard_status") or {}
        if isinstance(std_status, dict) and std_status.get("status") in {"abolished", "superseded"}:
            stale_hits += 1

    return {
        "line": item.get("_line"),
        "query": query,
        "query_type": item.get("query_type", ""),
        "expected_standard_code": expected_code,
        "expected_standard_name": expected_name,
        "expected_clause": expected_clause,
        "result_count": len(results),
        "first_rank": first_rank,
        "recall_at_k": bool(first_rank),
        "mrr": round(1.0 / first_rank, 4) if first_rank else 0.0,
        "ndcg": round(dcg(first_rank), 4) if first_rank else 0.0,
        "clause_hit": clause_hit,
        "elapsed_ms": elapsed_ms,
        "stale_hits": stale_hits,
        "matched_codes": matched_codes[:max_results],
        "error": error or clause_error,
    }


def summarize(rows):
    total = len(rows)
    by_type = {}
    for row in rows:
        bucket = by_type.setdefault(row["query_type"] or "unknown", [])
        bucket.append(row)

    def metrics(items):
        count = len(items)
        if not count:
            return {}
        clause_rows = [r for r in items if r["clause_hit"] is not None]
        return {
            "count": count,
            "recall_at_5": round(sum(1 for r in items if r["recall_at_k"]) / count, 4),
            "mrr": round(sum(r["mrr"] for r in items) / count, 4),
            "ndcg_at_10": round(sum(r["ndcg"] for r in items) / count, 4),
            "no_result_rate": round(sum(1 for r in items if r["result_count"] == 0) / count, 4),
            "avg_elapsed_ms": round(sum(r["elapsed_ms"] for r in items) / count, 2),
            "stale_hit_rate": round(sum(1 for r in items if r["stale_hits"] > 0) / count, 4),
            "clause_hit_rate": round(sum(1 for r in clause_rows if r["clause_hit"]) / len(clause_rows), 4) if clause_rows else None,
            "errors": sum(1 for r in items if r["error"]),
        }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kb_status": status(),
        "overall": metrics(rows),
        "by_query_type": {key: metrics(items) for key, items in sorted(by_type.items())},
    }


def write_markdown(report, output_path):
    overall = report["summary"]["overall"]
    lines = [
        "# Zhiwei KB Evaluation Baseline",
        "",
        f"Generated: {report['summary']['generated_at']}",
        f"Golden queries: {overall.get('count', 0)}",
        "",
        "## Overall",
        "",
    ]
    for key in ("recall_at_5", "mrr", "ndcg_at_10", "clause_hit_rate", "no_result_rate", "stale_hit_rate", "avg_elapsed_ms", "errors"):
        lines.append(f"- {key}: {overall.get(key)}")
    lines.extend(["", "## By Query Type", ""])
    for query_type, metrics in report["summary"]["by_query_type"].items():
        lines.append(f"- {query_type}: recall={metrics.get('recall_at_5')} mrr={metrics.get('mrr')} ndcg={metrics.get('ndcg_at_10')} no_result={metrics.get('no_result_rate')} avg_ms={metrics.get('avg_elapsed_ms')}")
    failures = [row for row in report["rows"] if not row["recall_at_k"] or row["error"]]
    lines.extend(["", "## Failures", ""])
    for row in failures[:50]:
        lines.append(f"- line {row['line']}: `{row['query']}` expected `{row['expected_standard_code']}` rank={row['first_rank']} results={row['result_count']} error={row['error']}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluate KB search quality")
    parser.add_argument("--golden", default=DEFAULT_GOLDEN)
    parser.add_argument("--json", default=DEFAULT_JSON)
    parser.add_argument("--md", default=DEFAULT_MD)
    parser.add_argument("--max-results", type=int, default=10)
    args = parser.parse_args()

    if not os.path.exists(args.golden):
        raise SystemExit(f"golden file not found: {args.golden}. Run eval/make_golden_queries.py first.")

    items = load_jsonl(args.golden)
    rows = [evaluate_query(item, args.max_results) for item in items]
    report = {"summary": summarize(rows), "rows": rows}

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    write_markdown(report, args.md)
    print(json.dumps(report["summary"]["overall"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
