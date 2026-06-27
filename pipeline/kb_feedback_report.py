# -*- coding: utf-8 -*-
"""Summarize KB feedback logs into optimization hints."""

import argparse
import collections
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDBACK_LOG = os.path.join(ROOT, "pipeline", "kb_feedback.jsonl")
OUTPUT_JSON = os.path.join(ROOT, "pipeline", "kb_feedback_report.json")
OUTPUT_MD = os.path.join(ROOT, "pipeline", "kb_feedback_report.md")


def load_entries(path):
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    entries.append(item)
            except json.JSONDecodeError:
                continue
    return entries


def analyze(entries):
    by_type = collections.Counter()
    by_branch = collections.Counter()
    by_status = collections.Counter()
    by_source = collections.Counter()
    missing_queries = []
    stale_queries = []
    for entry in entries:
        by_type[entry.get("type", "unknown")] += 1
        by_branch[entry.get("branch", entry.get("trace", {}).get("branch", "unknown"))] += 1
        by_status[entry.get("status", "unknown")] += 1
        by_source[entry.get("source", "unknown")] += 1
        if entry.get("type") == "missing":
            missing_queries.append(entry.get("query", ""))
        if entry.get("type") == "stale_version":
            stale_queries.append(entry.get("query", ""))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "entries": len(entries),
        "by_type": dict(by_type),
        "by_branch": dict(by_branch),
        "by_status": dict(by_status),
        "by_source": dict(by_source),
        "missing_queries": missing_queries[:50],
        "stale_queries": stale_queries[:50],
    }


def write_markdown(report, output_path):
    lines = [
        "# KB Feedback Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Entries: {report['entries']}",
        "",
        "## By Type",
        "",
    ]
    for key, value in sorted(report["by_type"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Branch", ""])
    for key, value in sorted(report["by_branch"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Status", ""])
    for key, value in sorted(report["by_status"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Missing Queries", ""])
    for query in report["missing_queries"]:
        lines.append(f"- `{query}`")
    lines.extend(["", "## Stale Version Queries", ""])
    for query in report["stale_queries"]:
        lines.append(f"- `{query}`")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Summarize KB feedback logs")
    parser.add_argument("--log", default=FEEDBACK_LOG)
    parser.add_argument("--json", default=OUTPUT_JSON)
    parser.add_argument("--md", default=OUTPUT_MD)
    args = parser.parse_args()
    entries = load_entries(args.log)
    report = analyze(entries)
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    write_markdown(report, args.md)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
