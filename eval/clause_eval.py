# -*- coding: utf-8 -*-
"""Evaluate structured clause objects returned by read_clause_full()."""

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in ("", "kb_core", "pipeline"):
    path = os.path.join(ROOT, rel) if rel else ROOT
    if path not in sys.path:
        sys.path.insert(0, path)

from kb_loader import read_clause_full  # noqa: E402

DEFAULT_SAMPLE = os.path.join(ROOT, "eval", "clause_golden_samples.json")
DEFAULT_JSON = os.path.join(ROOT, "eval", "clause_eval_report.json")
DEFAULT_MD = os.path.join(ROOT, "eval", "clause_eval_report.md")


def load_samples(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("clause sample file must be a JSON array")
    return data


def evaluate_sample(sample):
    data = read_clause_full(sample["standard_code"], sample["clause"])
    if not data:
        return {
            "standard_code": sample["standard_code"],
            "clause": sample["clause"],
            "ok": False,
            "reason": "not_found",
            "flag_hits": [],
            "flag_misses": sample.get("expected_flags", []),
        }
    if data.get("error"):
        return {
            "standard_code": sample["standard_code"],
            "official_code": data.get("official_code", ""),
            "clause": sample["clause"],
            "ok": False,
            "reason": data.get("error", "clause_error"),
            "clause_type": data.get("clause_type", "unknown"),
            "expected_clause_type": sample.get("expected_clause_type", ""),
            "flag_hits": [],
            "flag_misses": sample.get("expected_flags", []),
            "content_flags": data.get("content_flags", {}),
            "text_len": len(data.get("clause_text", "")),
            "confidence": data.get("confidence", ""),
            "source_file": data.get("source_file", ""),
        }
    flags = data.get("content_flags", {}) if isinstance(data, dict) else {}
    expected_flags = sample.get("expected_flags", [])
    hits = [flag for flag in expected_flags if flags.get(flag)]
    misses = [flag for flag in expected_flags if not flags.get(flag)]
    clause_type = data.get("clause_type", "unknown")
    text_len = len(data.get("clause_text", ""))
    type_ok = clause_type == sample.get("expected_clause_type", clause_type)
    length_ok = text_len >= sample.get("min_text_len", 0)
    ok = type_ok and not misses and length_ok
    reasons = []
    if not type_ok:
        reasons.append("type_mismatch")
    if misses:
        reasons.append("missing_flags")
    if not length_ok:
        reasons.append("text_too_short")
    citation = data.get("citation", {})
    citation_type = citation.get("clause_type", "unknown")
    citation_type_ok = citation_type == clause_type
    if not citation_type_ok:
        ok = False
        reasons.append("citation_type_mismatch")
    return {
        "standard_code": sample["standard_code"],
        "official_code": data.get("official_code", ""),
        "clause": sample["clause"],
        "ok": ok,
        "reason": "" if ok else ";".join(reasons),
        "clause_type": clause_type,
        "expected_clause_type": sample.get("expected_clause_type", ""),
        "flag_hits": hits,
        "flag_misses": misses,
        "content_flags": flags,
        "text_len": text_len,
        "confidence": data.get("confidence", ""),
        "source_file": data.get("source_file", ""),
        "source_heading": data.get("source_heading", ""),
        "matched_clause_line": data.get("matched_clause_line", ""),
        "match_method": data.get("match_method", ""),
        "version_status": data.get("version_status", {}).get("status", ""),
        "citation_clause_type": citation_type,
        "citation_audit_status": citation.get("audit_status", ""),
        "citation_required_missing": [
            key for key in ["standard_code", "clause_no", "quote_text", "source_file", "version_status", "audit_status"]
            if not citation.get(key)
        ],
    }


def summarize(rows):
    total = len(rows)
    ok_count = sum(1 for row in rows if row["ok"])
    type_mismatch = sum(1 for row in rows if row.get("reason") == "flag_or_type_mismatch")
    type_mismatch = sum(1 for row in rows if "type_mismatch" in row.get("reason", ""))
    missing_flags = sum(1 for row in rows if "missing_flags" in row.get("reason", ""))
    text_too_short = sum(1 for row in rows if "text_too_short" in row.get("reason", ""))
    not_found = sum(1 for row in rows if row.get("reason") in {"not_found", "clause_not_found"})
    missing_source_file = sum(1 for row in rows if row.get("ok") and not row.get("source_file"))
    missing_match_method = sum(1 for row in rows if row.get("ok") and not row.get("match_method"))
    missing_version_status = sum(1 for row in rows if row.get("ok") and not row.get("version_status"))
    missing_citation_audit_status = sum(1 for row in rows if row.get("ok") and not row.get("citation_audit_status"))
    missing_citation_required = sum(1 for row in rows if row.get("ok") and row.get("citation_required_missing"))
    citation_type_mismatch = sum(1 for row in rows if "citation_type_mismatch" in row.get("reason", ""))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "ok": ok_count,
        "pass_rate": round(ok_count / total, 4) if total else 0.0,
        "type_mismatch": type_mismatch,
        "missing_flags": missing_flags,
        "text_too_short": text_too_short,
        "not_found": not_found,
        "missing_source_file": missing_source_file,
        "missing_match_method": missing_match_method,
        "missing_version_status": missing_version_status,
        "missing_citation_audit_status": missing_citation_audit_status,
        "missing_citation_required": missing_citation_required,
        "citation_type_mismatch": citation_type_mismatch,
    }


def write_markdown(summary, rows, output_path):
    lines = [
        "# Clause Object Evaluation",
        "",
        f"Generated: {summary['generated_at']}",
        f"Total: {summary['total']}",
        f"Pass rate: {summary['pass_rate']}",
        f"Type mismatch: {summary['type_mismatch']}",
        f"Missing flags: {summary['missing_flags']}",
        f"Text too short: {summary['text_too_short']}",
        f"Not found: {summary['not_found']}",
        f"Missing source file: {summary['missing_source_file']}",
        f"Missing match method: {summary['missing_match_method']}",
        f"Missing version status: {summary['missing_version_status']}",
        f"Missing citation audit status: {summary['missing_citation_audit_status']}",
        f"Missing citation required fields: {summary['missing_citation_required']}",
        f"Citation type mismatch: {summary['citation_type_mismatch']}",
        "",
        "## Failures",
        "",
    ]
    for row in rows:
        if row["ok"]:
            continue
        lines.append(f"- `{row['standard_code']}` `{row['clause']}` reason={row['reason']} hits={','.join(row.get('flag_hits', []))} misses={','.join(row.get('flag_misses', []))}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluate structured clause objects")
    parser.add_argument("--samples", default=DEFAULT_SAMPLE)
    parser.add_argument("--json", default=DEFAULT_JSON)
    parser.add_argument("--md", default=DEFAULT_MD)
    args = parser.parse_args()
    samples = load_samples(args.samples)
    rows = [evaluate_sample(sample) for sample in samples]
    summary = summarize(rows)
    report = {"summary": summary, "rows": rows}
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    write_markdown(summary, rows, args.md)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
