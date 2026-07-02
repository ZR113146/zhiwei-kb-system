# -*- coding: utf-8 -*-
"""Standard status helpers for Zhiwei KB.

This module is intentionally lightweight: it only reads metadata generated from
kb.json-resolved paths and never edits source knowledge-base markdown files.
"""

import json
import os
import re

# 标准编号归一化真源在 kb_core.code_norm (零依赖, 全项目唯一真源)。
# 此处 re-export 保持向后兼容: `from kb_core.standard_status import
# normalize_code/official_code/extract_standard` 不变。
from kb_core.code_norm import (  # noqa: F401  (re-export)
    normalize_code,
    official_code,
    extract_standard,
)

_STATUS_FILE = "standard_status.json"


def status_path(kb_json_dir):
    return os.path.join(kb_json_dir, _STATUS_FILE)


def load_standard_status(kb_json_dir):
    path = status_path(kb_json_dir)
    if not os.path.exists(path):
        return {"_meta": {"missing": True}, "standards": {}, "aliases": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"_meta": {"invalid": True}, "standards": {}, "aliases": {}}
    data.setdefault("_meta", {})
    data.setdefault("standards", {})
    data.setdefault("aliases", {})
    return data


def status_for_code(status_data, code):
    standards = (status_data or {}).get("standards", {})
    aliases = (status_data or {}).get("aliases", {})
    normalized = normalize_code(code)
    canonical = aliases.get(normalized, normalized)
    record = standards.get(canonical)
    if not record:
        return {
            "status": "unknown",
            "standard_code": normalized or code or "",
            "confidence": "missing",
        }
    compact = {
        "status": record.get("status", "unknown"),
        "standard_code": record.get("standard_code", canonical),
        "official_code": record.get("official_code", record.get("display_code", "")),
        "standard_name": record.get("standard_name", ""),
        "year": record.get("year"),
        "effective_date": record.get("effective_date", ""),
        "abolished_date": record.get("abolished_date", ""),
        "replaced_by": record.get("replaced_by", []),
        "standard_level": record.get("standard_level", "unknown"),
        "jurisdiction": record.get("jurisdiction", ""),
        "confidence": record.get("confidence", "generated"),
        "evidence_url": record.get("evidence_url", ""),
        "evidence_urls": record.get("evidence_urls", ""),
        "evidence_source": record.get("evidence_source", ""),
        "evidence_scope": record.get("evidence_scope", ""),
        "review_note": record.get("review_note", ""),
    }
    if canonical != normalized:
        compact["resolved_from"] = normalized
    return compact


def coverage(status_data):
    standards = (status_data or {}).get("standards", {})
    aliases = (status_data or {}).get("aliases", {})
    total = len(standards)
    by_status = {}
    for record in standards.values():
        status = record.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    known = total - by_status.get("unknown", 0)
    return {
        "records": total,
        "aliases": len(aliases),
        "known_status": known,
        "unknown_status": by_status.get("unknown", 0),
        "coverage_ratio": round(known / total, 4) if total else 0.0,
        "by_status": by_status,
    }
