# -*- coding: utf-8 -*-
"""Generate calibration hints for clause object golden samples."""

import argparse
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPORT = os.path.join(ROOT, "eval", "clause_eval_report.json")
DEFAULT_MD = os.path.join(ROOT, "eval", "clause_calibration.md")
DEFAULT_JSON = os.path.join(ROOT, "eval", "clause_calibration.json")


def load_report(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def hint_for_row(row):
    reason = row.get("reason", "")
    if "clause_not_found" in reason or reason == "not_found":
        action = "verify_clause_number"
        note = "Clause lookup returned no text. Confirm the clause number exists in the indexed MD, or replace sample with a known indexed clause."
    elif "text_too_short" in reason and not row.get("flag_misses"):
        action = "lower_min_text_len"
        note = "Clause text is valid but shorter than the sample threshold. Lower min_text_len or choose a richer clause."
    elif "missing_flags" in reason:
        action = "review_expected_flags"
        note = "Returned clause did not contain expected feature flags. Remove unsupported flags or choose a clause that contains those signals."
    elif "type_mismatch" in reason:
        action = "review_expected_type"
        note = "Clause type differs from expectation. Confirm whether the clause is normative, commentary, appendix, table, or unknown."
    else:
        action = "review_manually"
        note = "Manual review recommended."
    return {
        "standard_code": row.get("standard_code", ""),
        "official_code": row.get("official_code", ""),
        "clause": row.get("clause", ""),
        "reason": reason,
        "action": action,
        "note": note,
        "text_len": row.get("text_len", 0),
        "flag_misses": row.get("flag_misses", []),
        "content_flags": row.get("content_flags", {}),
        "source_file": row.get("source_file", ""),
    }


def build_hints(report):
    rows = report.get("rows", [])
    return [hint_for_row(row) for row in rows if not row.get("ok")]


def write_md(hints, output_path):
    lines = [
        "# Clause Sample Calibration",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Hints: {len(hints)}",
        "",
    ]
    for hint in hints:
        lines.extend([
            f"## {hint['official_code'] or hint['standard_code']} {hint['clause']}",
            "",
            f"- action: `{hint['action']}`",
            f"- reason: `{hint['reason']}`",
            f"- text_len: {hint['text_len']}",
            f"- flag_misses: {', '.join(hint['flag_misses'])}",
            f"- source_file: `{hint['source_file']}`",
            f"- note: {hint['note']}",
            "",
        ])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Generate clause sample calibration hints")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--json", default=DEFAULT_JSON)
    parser.add_argument("--md", default=DEFAULT_MD)
    args = parser.parse_args()
    hints = build_hints(load_report(args.report))
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"), "hints": hints}, f, ensure_ascii=False, indent=2)
    write_md(hints, args.md)
    print(json.dumps({"hints": len(hints), "json": args.json, "md": args.md}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
