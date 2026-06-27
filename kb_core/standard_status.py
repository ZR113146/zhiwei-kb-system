# -*- coding: utf-8 -*-
"""Standard status helpers for Zhiwei KB.

This module is intentionally lightweight: it only reads metadata generated from
kb.json-resolved paths and never edits source knowledge-base markdown files.
"""

import json
import os
import re
from datetime import datetime

_STATUS_FILE = "standard_status.json"
_CURRENT_YEAR = datetime.now().year

_CODE_RE = re.compile(
    r"(TCECS|CECS|CJJ_T|CJJT|CJJ|CJ_T|CJT|CJ|JGJ_T|JGJT|JGJ|GB_T|GBT|GB|JTG_T|JTGT|JTG|JC_T|JCT|JC|DB\d{2}_T|DB\d{2}T|DB\d{2}|DB)"
    r"[\s_/-]*(?:T[\s_/-]*)?([A-Z]?\d+(?:\.\d+)?)"
    r"(?:[\s_-]*(19\d{2}|20\d{2}))?",
    re.IGNORECASE,
)


def normalize_code(raw):
    if not raw:
        return ""
    text = str(raw).upper().replace("／", "/")
    text = re.sub(r"\s+", " ", text).strip()
    match = _CODE_RE.search(text)
    if not match:
        return ""
    prefix, number, _year = match.groups()
    raw_token = match.group(0).upper().replace(" ", "")
    prefix = prefix.replace("_", "").replace("/", "")
    recommended = "/T" in raw_token or "_T" in raw_token or prefix.endswith("T")
    if recommended and not prefix.endswith("T") and prefix not in {"TCECS"}:
        prefix = f"{prefix}T"
    return f"{prefix}{number}"


def official_code(raw):
    """Return the human-readable official code while keeping standard_code file-safe.

    Examples: GB_T 50107-2010 -> GB/T 50107-2010; JGJ_T 23-2011 -> JGJ/T 23-2011.
    """
    text = str(raw or "").upper().replace("／", "/")
    match = _CODE_RE.search(text)
    if not match:
        return ""
    prefix, number, year = match.groups()
    raw_token = match.group(0).upper().replace("_", "/")
    prefix = prefix.replace("_", "").replace("/", "")
    if "/T" in raw_token and not prefix.endswith("T"):
        official_prefix = f"{prefix}/T"
    elif prefix.endswith("T") and prefix not in {"TCECS"}:
        official_prefix = f"{prefix[:-1]}/T"
    else:
        official_prefix = prefix
    suffix = f"-{year}" if year else ""
    return f"{official_prefix} {number}{suffix}"


def extract_standard(raw):
    text = str(raw or "")
    match = _CODE_RE.search(text)
    if not match:
        return None
    prefix, number, year = match.groups()
    code = normalize_code(match.group(0))
    name = text[match.end():]
    name = re.sub(r"\.(json|md)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^[_\s-]+", "", name)
    name = re.sub(r"_p\d{4}-\d{4}$", "", name)
    name = name.strip() or text.strip()
    return {
        "standard_code": code,
        "display_code": match.group(0).strip(),
        "official_code": official_code(match.group(0)),
        "standard_name": name,
        "year": int(year) if year else None,
    }


def infer_level(code):
    code = (code or "").upper()
    if code.startswith(("GB", "GBT")):
        return "national"
    if code.startswith(("JGJ", "CJJ", "JTG", "JC")):
        return "industry"
    if code.startswith("DB"):
        return "local"
    if code.startswith(("CECS", "TCECS")):
        return "association"
    return "unknown"


def infer_default_status(year):
    if not year:
        return "unknown"
    if year >= _CURRENT_YEAR - 12:
        return "effective"
    return "unknown"


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


def build_records_from_manifest(manifest):
    records = {}
    standards = manifest.get("standards", {}) if isinstance(manifest, dict) else {}
    for name, filename in standards.items():
        source = filename or name
        extracted = extract_standard(source) or extract_standard(name)
        if not extracted:
            continue
        code = extracted["standard_code"]
        if not code:
            continue
        current = records.get(code, {})
        year = extracted.get("year") or current.get("year")
        record = {
            "standard_code": code,
            "display_code": extracted.get("display_code", current.get("display_code", code)),
            "official_code": extracted.get("official_code", current.get("official_code", current.get("display_code", code))),
            "standard_name": extracted.get("standard_name") or current.get("standard_name", ""),
            "year": year,
            "status": current.get("status") or infer_default_status(year),
            "effective_date": current.get("effective_date", ""),
            "abolished_date": current.get("abolished_date", ""),
            "replaced_by": current.get("replaced_by", []),
            "standard_level": current.get("standard_level") or infer_level(code),
            "jurisdiction": current.get("jurisdiction", "CN" if not code.startswith("DB") else "local"),
            "confidence": current.get("confidence", "generated_from_manifest"),
            "evidence_url": current.get("evidence_url", ""),
            "evidence_urls": current.get("evidence_urls", ""),
            "evidence_source": current.get("evidence_source", ""),
            "evidence_scope": current.get("evidence_scope", ""),
            "review_note": current.get("review_note", ""),
            "source": current.get("source", source),
        }
        records[code] = record
    return dict(sorted(records.items()))
