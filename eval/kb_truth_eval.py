# -*- coding: utf-8 -*-
"""Evaluate Zhiwei KB search results against manually reviewed truth queries."""

import argparse
import collections
import json
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

from kb_loader import search, status  # noqa: E402
import support_guard as shared_support_guard  # noqa: E402

DEFAULT_TRUTH = os.path.join(ROOT, "eval", "truth_queries_seed.jsonl")
DEFAULT_JSON = os.path.join(ROOT, "eval", "truth_baseline_report.json")
DEFAULT_MD = os.path.join(ROOT, "eval", "truth_baseline_report.md")
DEFAULT_FAILURE_MD = os.path.join(ROOT, "eval", "truth_failure_analysis.md")



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


# Support-judgment primitives live in kb_core.support_guard so production
# annotations and truth evaluation cannot drift apart.
compact_code = shared_support_guard.compact_code
normalize_text = shared_support_guard.normalize_text
normalize_unit_text = shared_support_guard.normalize_unit_text
normalize_number = shared_support_guard.normalize_number
result_text = shared_support_guard.result_text
result_code = shared_support_guard.result_code
clause_tokens = shared_support_guard.clause_tokens
text_has_clause = shared_support_guard.text_has_clause
split_condition_tokens = shared_support_guard.split_condition_tokens
value_unit_hit = shared_support_guard.value_unit_hit
text_has_table_context = shared_support_guard.text_has_table_context
text_has_fact = shared_support_guard.text_has_fact
result_is_stale = shared_support_guard.result_is_stale
result_has_deleted_marker = shared_support_guard.result_has_deleted_marker
required_clause_matches = shared_support_guard.required_clause_matches
alternative_matches = shared_support_guard.alternative_matches
forbidden_matches = shared_support_guard.forbidden_matches
build_evidence = shared_support_guard.build_evidence
evaluate_result_support = shared_support_guard.evaluate_result_support
support_adjusted_score = shared_support_guard.support_adjusted_score
simulate_support_guarded_results = shared_support_guard.simulate_support_guarded_results
def evaluate_at_k(item, results, top_k):
    selected = results[:top_k]
    required = item.get("required_clauses") or []
    alternatives = item.get("acceptable_alternatives") or []
    facts = item.get("required_facts") or []
    forbidden = item.get("forbidden_hits") or []
    evidence = build_evidence(results, top_k)

    if required:
        standard_hit = False
        clause_hit = False
        for result in selected:
            for clause in required:
                standard_match, clause_match = required_clause_matches(result, clause)
                standard_hit = standard_hit or standard_match
                clause_hit = clause_hit or (standard_match and clause_match)
            for alternative in alternatives:
                if alternative_matches(result, alternative):
                    standard_hit = True
                    clause_hit = True
    else:
        standard_hit = bool(selected)
        clause_hit = bool(selected)

    fact_hit = all(text_has_fact(evidence, fact, item.get("query_type", "")) for fact in facts) if facts else True
    forbidden_hit = any(forbidden_matches(result, item) for result in selected for item in forbidden)
    stale_hit = any(result_is_stale(result) for result in selected)
    deleted_clause_hit = any(result_has_deleted_marker(result) for result in selected)

    required_deleted = any(str(clause.get("clause_type", "")).lower() == "deleted" for clause in required)
    version_ok = not stale_hit and (required_deleted or not deleted_clause_hit)
    support_ok = bool(selected) and standard_hit and clause_hit and fact_hit and version_ok and not forbidden_hit
    answerability = support_ok and len(evidence.strip()) >= 20

    reasons = []
    if not selected:
        reasons.append("no_results")
    if not standard_hit:
        reasons.append("standard_not_hit")
    if not clause_hit:
        reasons.append("clause_not_hit")
    if not fact_hit:
        reasons.append("required_fact_not_hit")
    if stale_hit:
        reasons.append("stale_standard_hit")
    if deleted_clause_hit and not required_deleted:
        reasons.append("deleted_clause_hit")
    if forbidden_hit:
        reasons.append("forbidden_hit")
    if support_ok and not answerability:
        reasons.append("not_answerable")

    return {
        "standard_hit": standard_hit,
        "clause_hit": clause_hit,
        "fact_hit": fact_hit,
        "version_ok": version_ok,
        "support_ok": support_ok,
        "forbidden_hit": forbidden_hit,
        "stale_hit": stale_hit,
        "deleted_clause_hit": deleted_clause_hit,
        "answerability": answerability,
        "reasons": reasons,
    }


def first_support_rank(item, results):
    for index in range(1, len(results) + 1):
        if evaluate_at_k(item, results, index)["support_ok"]:
            return index
    return None


def classify_failure(row):
    reasons = set(row.get("reasons_at_3") or row.get("reasons_at_1") or [])
    query_type = row.get("query_type", "")
    if row.get("error"):
        return "runtime_error"
    if "forbidden_hit" in reasons or "deleted_clause_hit" in reasons or "stale_standard_hit" in reasons:
        return "version_or_forbidden_failure"
    if "no_results" in reasons or "standard_not_hit" in reasons:
        return "recall_failure"
    if "clause_not_hit" in reasons:
        return "clause_location_failure"
    if "required_fact_not_hit" in reasons:
        if query_type == "table_cell":
            return "table_location_failure"
        return "fact_support_failure"
    if query_type in {"broad_technical", "explanation_vs_normative"}:
        return "sample_or_review_needed"
    return "ranking_or_support_failure"


def evaluate_query(item, max_results):
    start = time.perf_counter()
    try:
        results = search(item["query"], max_results=max_results)
        error = ""
    except Exception as exc:
        results = []
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

    at1 = evaluate_at_k(item, results, 1)
    at3 = evaluate_at_k(item, results, min(3, max_results))
    first_rank = first_support_rank(item, results)

    first_results = []
    for index, result in enumerate(results[:max_results], 1):
        support_signals = evaluate_result_support(item, result)
        first_results.append({
            "rank": index,
            "standard_code": result.get("standard_code", ""),
            "heading": result.get("heading", ""),
            "score": result.get("score", 0),
            "rank_source": result.get("rank_source", ""),
            "standard_status": (result.get("standard_status") or {}).get("status", "") if isinstance(result.get("standard_status"), dict) else "",
            "trace": result.get("_trace", {}),
            "support_judgment": support_signals["support_judgment"],
            "support_action": support_signals["support_action"],
            "support_signals": support_signals,
            "text_preview": str(result.get("text", ""))[:180].replace("\n", " "),
        })

    simulated_results = simulate_support_guarded_results(first_results)
    original_top = first_results[0] if first_results else {}
    simulated_top = simulated_results[0] if simulated_results else {}
    simulated_top_support_ok = bool(simulated_top.get("support_signals", {}).get("support_ok"))

    row = {
        "line": item.get("_line"),
        "id": item.get("id", ""),
        "query": item.get("query", ""),
        "query_type": item.get("query_type", ""),
        "review_status": item.get("review_status", ""),
        "result_count": len(results),
        "first_support_rank": first_rank,
        "truth_support_at_1": at1["support_ok"],
        "truth_support_at_3": at3["support_ok"],
        "clause_at_3": at3["clause_hit"],
        "fact_at_3": at3["fact_hit"],
        "version_ok_at_3": at3["version_ok"],
        "forbidden_hit_at_3": at3["forbidden_hit"],
        "deleted_clause_hit_at_3": at3["deleted_clause_hit"],
        "stale_hit_at_3": at3["stale_hit"],
        "answerability_at_3": at3["answerability"],
        "unsupported_high_score": bool(results) and not at1["support_ok"],
        "simulated_truth_support_at_1": simulated_top_support_ok,
        "simulated_unsupported_high_score": bool(simulated_results) and not simulated_top_support_ok,
        "support_guard_top1_changed": bool(original_top and simulated_top and original_top.get("rank") != simulated_top.get("original_rank")),
        "reasons_at_1": at1["reasons"],
        "reasons_at_3": at3["reasons"],
        "elapsed_ms": elapsed_ms,
        "error": error,
        "top_results": first_results,
        "support_guarded_results": simulated_results,
    }
    row["failure_category"] = "supported" if row["truth_support_at_3"] else classify_failure(row)
    return row


def rate(rows, predicate):
    if not rows:
        return None
    return round(sum(1 for row in rows if predicate(row)) / len(rows), 4)


def summarize(rows):
    total = len(rows)
    by_type = collections.defaultdict(list)
    by_failure = collections.Counter()
    for row in rows:
        by_type[row.get("query_type") or "unknown"].append(row)
        by_failure[row.get("failure_category") or "unknown"] += 1

    def metrics(items):
        if not items:
            return {}
        table_items = [row for row in items if row.get("query_type") == "table_cell"]
        return {
            "count": len(items),
            "TruthSupport@1": rate(items, lambda row: row["truth_support_at_1"]),
            "TruthSupport@3": rate(items, lambda row: row["truth_support_at_3"]),
            "Clause@3": rate(items, lambda row: row["clause_at_3"]),
            "Fact@3": rate(items, lambda row: row["fact_at_3"]),
            "ForbiddenHitRate": rate(items, lambda row: row["forbidden_hit_at_3"]),
            "DeletedClauseErrorRate": rate(items, lambda row: row["deleted_clause_hit_at_3"]),
            "StaleVersionErrorRate": rate(items, lambda row: row["stale_hit_at_3"]),
            "TableCellHitRate": rate(table_items, lambda row: row["truth_support_at_3"]) if table_items else None,
            "UnsupportedHighScoreRate": rate(items, lambda row: row["unsupported_high_score"]),
            "SimulatedTruthSupport@1": rate(items, lambda row: row["simulated_truth_support_at_1"]),
            "SimulatedUnsupportedHighScoreRate": rate(items, lambda row: row["simulated_unsupported_high_score"]),
            "SupportGuardTop1ChangedRate": rate(items, lambda row: row["support_guard_top1_changed"]),
            "UnsupportedHighScoreGuardedRate": rate(
                [row for row in items if row["unsupported_high_score"]],
                lambda row: (row["top_results"] and row["top_results"][0].get("support_action") != "use_as_evidence"),
            ),
            "ForbiddenBlockedRate": rate(
                [row for row in items if row["forbidden_hit_at_3"] or row["deleted_clause_hit_at_3"] or row["stale_hit_at_3"]],
                lambda row: any(item.get("support_action") == "block_forbidden" for item in row["top_results"][:3]),
            ),
            "EvidenceUseRate": rate(items, lambda row: bool(row["top_results"] and row["top_results"][0].get("support_action") == "use_as_evidence")),
            "ManualReviewRate": rate(items, lambda row: bool(row["top_results"] and row["top_results"][0].get("support_action") == "manual_review")),
            "SimulatedBlockedTop1Rate": rate(items, lambda row: bool(row["support_guarded_results"] and row["support_guarded_results"][0].get("support_action") == "block_forbidden")),
            "AvgLatency": round(sum(row["elapsed_ms"] for row in items) / len(items), 2),
            "Errors": sum(1 for row in items if row["error"]),
        }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kb_status": status(),
        "total": total,
        "overall": metrics(rows),
        "by_query_type": {key: metrics(value) for key, value in sorted(by_type.items())},
        "by_failure_category": dict(sorted(by_failure.items())),
    }


def write_markdown(report, output_path):
    summary = report["summary"]
    overall = summary["overall"]
    lines = [
        "# Zhiwei KB Truth Baseline",
        "",
        f"Generated: {summary['generated_at']}",
        f"Truth queries: {summary['total']}",
        "",
        "## Overall",
        "",
    ]
    for key in ("TruthSupport@1", "TruthSupport@3", "Clause@3", "Fact@3", "ForbiddenHitRate", "DeletedClauseErrorRate", "StaleVersionErrorRate", "TableCellHitRate", "UnsupportedHighScoreRate", "AvgLatency", "Errors"):
        lines.append(f"- {key}: {overall.get(key)}")
    for key in ("UnsupportedHighScoreGuardedRate", "SimulatedTruthSupport@1", "SimulatedUnsupportedHighScoreRate", "SupportGuardTop1ChangedRate", "ForbiddenBlockedRate", "EvidenceUseRate", "ManualReviewRate", "SimulatedBlockedTop1Rate"):
        lines.append(f"- {key}: {overall.get(key)}")

    lines.extend(["", "## By Query Type", ""])
    for query_type, metrics in summary["by_query_type"].items():
        lines.append(
            f"- {query_type}: support@1={metrics.get('TruthSupport@1')} "
            f"support@3={metrics.get('TruthSupport@3')} clause@3={metrics.get('Clause@3')} "
            f"fact@3={metrics.get('Fact@3')} unsupported_high={metrics.get('UnsupportedHighScoreRate')} "
            f"avg_ms={metrics.get('AvgLatency')}"
        )

    lines.extend(["", "## Failure Categories", ""])
    for category, count in summary["by_failure_category"].items():
        lines.append(f"- {category}: {count}")

    lines.extend(["", "## Failed Or Risky Queries", ""])
    for row in report["rows"]:
        if row["truth_support_at_3"] and not row["unsupported_high_score"]:
            continue
        top = row["top_results"][0] if row["top_results"] else {}
        simulated_top = row["support_guarded_results"][0] if row["support_guarded_results"] else {}
        lines.append(
            f"- {row['id']} `{row['query']}`: category={row['failure_category']} "
            f"support@3={row['truth_support_at_3']} reasons={','.join(row['reasons_at_3']) or '-'} "
            f"top={top.get('standard_code', '')} {top.get('heading', '')} "
            f"judgment={top.get('support_judgment', '')} missing={','.join(top.get('support_signals', {}).get('missing_dimensions', [])) or '-'}"
            f" action={top.get('support_action', '')}"
            f" simulated_top={simulated_top.get('standard_code', '')} {simulated_top.get('heading', '')}"
            f" simulated_action={simulated_top.get('support_action', '')}"
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_failure_analysis(report, output_path):
    rows = report["rows"]
    failures = [row for row in rows if not row["truth_support_at_3"]]
    counter = collections.Counter(row["failure_category"] for row in failures)
    risk_order = [
        "version_or_forbidden_failure",
        "fact_support_failure",
        "table_location_failure",
        "clause_location_failure",
        "recall_failure",
        "sample_or_review_needed",
        "ranking_or_support_failure",
    ]
    ranked = sorted(counter.items(), key=lambda item: (risk_order.index(item[0]) if item[0] in risk_order else 99, -item[1]))
    top_focus = [category for category, _ in ranked[:3]]

    lines = [
        "# Truth Failure Analysis",
        "",
        f"Generated: {report['summary']['generated_at']}",
        f"Failed queries at @3: {len(failures)} / {len(rows)}",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in sorted(counter.items()):
        lines.append(f"- {category}: {count}")

    lines.extend(["", "## Recommended T4 Focus", ""])
    if top_focus:
        for category in top_focus:
            lines.append(f"- {category}")
    else:
        lines.append("- No failing category selected.")

    lines.extend(["", "## Per Query Attribution", ""])
    for row in rows:
        if row["truth_support_at_3"]:
            continue
        top = row["top_results"][0] if row["top_results"] else {}
        simulated_top = row["support_guarded_results"][0] if row["support_guarded_results"] else {}
        lines.append(
            f"- {row['id']} `{row['query']}`: {row['failure_category']}; "
            f"reasons={','.join(row['reasons_at_3']) or '-'}; "
            f"top={top.get('standard_code', '')} {top.get('heading', '')}; "
            f"rank_source={top.get('rank_source', '')}; status={top.get('standard_status', '')}; "
            f"judgment={top.get('support_judgment', '')}; "
            f"action={top.get('support_action', '')}; "
            f"missing={','.join(top.get('support_signals', {}).get('missing_dimensions', [])) or '-'}"
            f"; simulated_top={simulated_top.get('standard_code', '')} {simulated_top.get('heading', '')}; "
            f"simulated_action={simulated_top.get('support_action', '')}; "
            f"simulated_weight={simulated_top.get('support_adjustment_weight', '')}; "
            f"simulated_score={simulated_top.get('support_adjusted_score', '')}"
        )

    lines.extend([
        "",
        "## Phase Questions",
        "",
        "1. This phase serves reliable professional answers by judging support against truth answers, not only search relevance.",
        "2. It validates deterministic standard/clause/fact/version/forbidden signals; it does not validate full semantic table reasoning or LLM answer grading.",
        "3. It does not extend plan writing, Word output, or generic search tuning.",
        "4. The most dangerous current error type is the highest-risk category listed in Recommended T4 Focus, especially forbidden/deleted or high-score unsupported evidence.",
        "5. Next step should target only the selected T4 categories because tuning before attribution would hide the actual failure mechanism.",
    ])

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluate KB truth-support quality")
    parser.add_argument("--truth", default=DEFAULT_TRUTH)
    parser.add_argument("--json", default=DEFAULT_JSON)
    parser.add_argument("--md", default=DEFAULT_MD)
    parser.add_argument("--failure-md", default=DEFAULT_FAILURE_MD)
    parser.add_argument("--max-results", type=int, default=10)
    args = parser.parse_args()

    if not os.path.exists(args.truth):
        raise SystemExit(f"truth file not found: {args.truth}")

    items = load_jsonl(args.truth)
    rows = [evaluate_query(item, args.max_results) for item in items]
    report = {"summary": summarize(rows), "rows": rows}

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    write_markdown(report, args.md)
    write_failure_analysis(report, args.failure_md)
    print(json.dumps(report["summary"]["overall"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
