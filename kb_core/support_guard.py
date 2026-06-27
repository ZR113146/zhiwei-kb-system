# -*- coding: utf-8 -*-
"""Truth-support guard for KB search results.

The guard is intentionally deterministic and optional. It reuses manually
reviewed truth-query records to annotate search results with support signals,
without making the core resolver depend on eval scripts.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from standard_status import normalize_code
except ImportError:  # pragma: no cover - module can also be imported as package
    from .standard_status import normalize_code


DELETED_MARKERS = ("本条删除", "本条已删除", "本条作废", "已废止", "鏈潯鍒犻櫎", "鏈潯宸插垹闄?")
STALE_STATUSES = {"abolished", "superseded"}
MOJIBAKE_DELETED_RE = re.compile(r"(?:鏈.|鏈.)?鏉.?(?:鍒犻櫎|垹闄)")
SUPPORT_ACTION_WEIGHTS = {
    "use_as_evidence": 1.0,
    "warn_insufficient_support": 0.75,
    "manual_review": 0.55,
    "block_forbidden": 0.1,
}
DEFAULT_SUPPORT_WEIGHT = 0.5


def compact_code(value: Any) -> str:
    text = str(value or "")
    return normalize_code(text) or re.sub(r"[^A-Z0-9.]", "", text.upper())


def normalize_unit_text(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "m²": "m2",
        "㎡": "m2",
        "m虏": "m2",
        "M虏": "m2",
        "銕?": "m2",
        "锝嶏紥": "m2",
        "虏": "2",
        "m^2": "m2",
        "m^{2}": "m2",
        "m 2": "m2",
        "平方": "m2",
        "m³": "m3",
        "㎥": "m3",
        "m鲁": "m3",
        "M鲁": "m3",
        "锝嶏紦": "m3",
        "鲁": "3",
        "m^3": "m3",
        "m^{3}": "m3",
        "m 3": "m3",
        "立方": "m3",
        "℃": "c",
        "鈩?": "c",
        "掳c": "c",
        "掳C": "c",
        "°c": "c",
        "°C": "c",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"m\s*\^\s*\{?2\}?", "m2", text, flags=re.IGNORECASE)
    text = re.sub(r"m\s*\^\s*\{?3\}?", "m3", text, flags=re.IGNORECASE)
    text = re.sub(r"m\s+([23])\b", r"m\1", text, flags=re.IGNORECASE)
    return text


def normalize_text(value: Any) -> str:
    text = normalize_unit_text(value)
    text = text.replace("\\mathrm", "")
    text = re.sub(r"[{}$]", "", text)
    return re.sub(r"\s+", "", text).lower()


def normalize_number(value: Any) -> str:
    return normalize_unit_text(value).replace(" ", "")


def result_text(result: Dict[str, Any]) -> str:
    parts = [
        result.get("file", ""),
        result.get("heading", ""),
        result.get("standard_code", ""),
        result.get("standard_name", ""),
        result.get("text", ""),
    ]
    status_data = result.get("standard_status") or {}
    if isinstance(status_data, dict):
        parts.extend(str(status_data.get(k, "") or "") for k in ("standard_code", "official_code", "standard_name", "status"))
    return "\n".join(str(part or "") for part in parts)


def result_code(result: Dict[str, Any]) -> str:
    for key in ("standard_code", "code"):
        code = compact_code(result.get(key))
        if code:
            return code
    status_data = result.get("standard_status") or {}
    if isinstance(status_data, dict):
        for key in ("standard_code", "official_code", "display_code"):
            code = compact_code(status_data.get(key))
            if code:
                return code
    return compact_code(result_text(result))


def clause_tokens(clause_no: Any) -> List[str]:
    clause = str(clause_no or "").strip()
    if not clause:
        return []
    tokens = {clause, f"第{clause}条", f"§{clause}"}
    if clause.upper() == "A":
        tokens.update({"附录A", "附录 A", "Appendix A"})
    return list(tokens)


def text_has_clause(text: str, clause_no: Any) -> bool:
    if not clause_no:
        return True
    normalized = normalize_text(text)
    for token in clause_tokens(clause_no):
        if normalize_text(token) in normalized:
            return True
    if str(clause_no).upper() == "A" and "附录" in text and "A" in text.upper():
        return True
    return False


def split_condition_tokens(condition: Any) -> List[str]:
    tokens = []
    for token in re.split(r"[、，,；;或和/\s]+", str(condition or "")):
        token = token.strip()
        if len(token) >= 2:
            tokens.append(token)
    return tokens


def value_unit_hit(text: str, value: Any, unit: Any) -> bool:
    if not value:
        return True
    normalized_text = normalize_text(text)
    normalized_value = normalize_number(value)
    normalized_unit = normalize_text(unit) if unit else ""
    if not normalized_value:
        return True
    value_forms = {normalized_value}
    if "." in normalized_value:
        value_forms.add(normalized_value.rstrip("0").rstrip("."))
    if normalized_unit:
        return any((value_form + normalized_unit) in normalized_text for value_form in value_forms if value_form)
    return any(value_form in normalized_text for value_form in value_forms if value_form)


def text_has_table_context(text: str, fact: Dict[str, Any]) -> bool:
    value = str(fact.get("value", "") or "")
    unit = str(fact.get("unit", "") or "")
    fact_text = str(fact.get("fact", "") or "")
    condition = str(fact.get("condition", "") or "")
    normalized = normalize_text(text)
    has_table = "<table" in str(text).lower() or "表" in str(text) or "table" in str(text).lower()
    if not has_table:
        return False

    normalized_value = normalize_number(value)
    value_forms = {normalized_value}
    if "." in normalized_value:
        value_forms.add(normalized_value.rstrip("0").rstrip("."))
    if normalized_value and not any(value_form and value_form in normalized for value_form in value_forms):
        return False

    normalized_unit = normalize_text(unit) if unit else ""
    if normalized_unit and normalized_unit not in normalized:
        return False

    cues = []
    generic_fragments = [normalize_text(cue) for cue in ("表格", "材料", "行列", "上下文", "或")]
    for token in split_condition_tokens(" ".join([fact_text, condition])):
        normalized_token = normalize_text(token)
        if not normalized_token or any(char.isdigit() for char in normalized_token):
            continue
        for fragment in generic_fragments:
            normalized_token = normalized_token.replace(fragment, "")
        if len(normalized_token) >= 2:
            cues.append(normalized_token)
    return True if not cues else any(cue in normalized for cue in cues)


def text_has_fact(text: str, fact: Dict[str, Any], query_type: str = "") -> bool:
    fact_text = str(fact.get("fact", "") or "")
    value = str(fact.get("value", "") or "")
    unit = str(fact.get("unit", "") or "")
    condition = str(fact.get("condition", "") or "")
    haystack = normalize_text(text)

    if query_type == "table_cell":
        return text_has_table_context(text, fact)

    if fact_text and normalize_text(fact_text) in haystack:
        return value_unit_hit(text, value, unit) if (value or unit) else True

    checks = []
    if value or unit:
        checks.append(value_unit_hit(text, value, unit))
    fact_tokens = split_condition_tokens(fact_text)
    if fact_tokens:
        checks.append(any(normalize_text(tok) in haystack for tok in fact_tokens))
    condition_tokens = split_condition_tokens(condition)
    if condition_tokens:
        checks.append(any(normalize_text(tok) in haystack for tok in condition_tokens))
    if not checks and any(marker in str(text) for marker in DELETED_MARKERS):
        return True
    return all(checks) if checks else True


def result_is_stale(result: Dict[str, Any]) -> bool:
    status_data = result.get("standard_status") or {}
    status_value = ""
    if isinstance(status_data, dict):
        status_value = str(status_data.get("status", "") or "").lower()
    return status_value in STALE_STATUSES


def result_has_deleted_marker(result: Dict[str, Any]) -> bool:
    text = result_text(result)
    return any(marker in text for marker in DELETED_MARKERS) or bool(MOJIBAKE_DELETED_RE.search(text))


def required_clause_matches(result: Dict[str, Any], clause: Dict[str, Any]) -> Tuple[bool, bool]:
    required_code = compact_code(clause.get("standard_code") or clause.get("official_code"))
    official_code = compact_code(clause.get("official_code"))
    code = result_code(result)
    text = result_text(result)
    standard_match = not required_code or required_code == code or official_code == code or required_code in compact_code(text)
    clause_match = text_has_clause(text, clause.get("clause_no", ""))
    return standard_match, clause_match


def alternative_matches(result: Dict[str, Any], alternative: Dict[str, Any]) -> bool:
    alt_code = compact_code(alternative.get("standard_code") or alternative.get("official_code"))
    code = result_code(result)
    if alt_code and alt_code != code and alt_code not in compact_code(result_text(result)):
        return False
    return text_has_clause(result_text(result), alternative.get("clause_no", ""))


def forbidden_matches(result: Dict[str, Any], forbidden: Dict[str, Any]) -> bool:
    forbidden_code = compact_code(forbidden.get("standard_code"))
    code = result_code(result)
    text = result_text(result)
    code_match = not forbidden_code or forbidden_code == code or forbidden_code in compact_code(text)
    clause_match = text_has_clause(text, forbidden.get("clause_no", ""))
    return code_match and clause_match


def build_evidence(results: List[Dict[str, Any]], top_k: int) -> str:
    return "\n".join(result_text(result) for result in results[:top_k])


def evaluate_result_support(truth_item: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    required = truth_item.get("required_clauses") or []
    alternatives = truth_item.get("acceptable_alternatives") or []
    facts = truth_item.get("required_facts") or []
    forbidden = truth_item.get("forbidden_hits") or []
    text = result_text(result)

    required_matches = [required_clause_matches(result, clause) for clause in required]
    standard_hit = any(match[0] for match in required_matches) if required else True
    clause_hit = any(match[0] and match[1] for match in required_matches) if required else True
    alternative_hit = any(alternative_matches(result, alternative) for alternative in alternatives)
    if alternative_hit:
        standard_hit = True
        clause_hit = True
    fact_hits = [text_has_fact(text, fact, truth_item.get("query_type", "")) for fact in facts]
    fact_hit = all(fact_hits) if facts else True
    forbidden_hit = any(forbidden_matches(result, item) for item in forbidden)
    stale_hit = result_is_stale(result)
    deleted_clause_hit = result_has_deleted_marker(result)
    required_deleted = any(str(clause.get("clause_type", "")).lower() == "deleted" for clause in required)
    version_ok = not stale_hit and (required_deleted or not deleted_clause_hit)
    support_ok = standard_hit and clause_hit and fact_hit and version_ok and not forbidden_hit

    missing = []
    if not standard_hit:
        missing.append("standard")
    if not clause_hit:
        missing.append("clause")
    if not fact_hit:
        missing.append("fact")
    if not version_ok:
        missing.append("version")
    if forbidden_hit:
        missing.append("forbidden")

    if support_ok:
        judgment = "supported"
    elif standard_hit or clause_hit or fact_hit:
        judgment = "insufficient_support"
    else:
        judgment = "manual_review"

    if forbidden_hit or stale_hit or (deleted_clause_hit and not required_deleted):
        action = "block_forbidden"
    elif support_ok:
        action = "use_as_evidence"
    elif judgment == "insufficient_support":
        action = "warn_insufficient_support"
    else:
        action = "manual_review"

    return {
        "standard_hit": standard_hit,
        "clause_hit": clause_hit,
        "alternative_hit": alternative_hit,
        "fact_hit": fact_hit,
        "fact_hits": fact_hits,
        "version_ok": version_ok,
        "forbidden_hit": forbidden_hit,
        "stale_hit": stale_hit,
        "deleted_clause_hit": deleted_clause_hit,
        "support_ok": support_ok,
        "support_judgment": judgment,
        "support_action": action,
        "missing_dimensions": missing,
    }


def support_adjusted_score(result: Dict[str, Any]) -> Tuple[float, float]:
    action = result.get("support_action", "")
    weight = SUPPORT_ACTION_WEIGHTS.get(action, DEFAULT_SUPPORT_WEIGHT)
    try:
        score = float(result.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    return round(score * weight, 6), weight


def support_action(result: Dict[str, Any]) -> str:
    raw = result.get("raw") or {}
    return str(result.get("support_action") or raw.get("support_action") or "")


def partition_by_support_action(results: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    usable = []
    review = []
    blocked = []
    for item in results:
        action = support_action(item)
        if action == "block_forbidden":
            blocked.append(item)
        elif action == "use_as_evidence" or not action:
            usable.append(item)
        else:
            review.append(item)
    return usable, review, blocked


def simulate_support_guarded_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    simulated = []
    for result in results:
        adjusted_score, weight = support_adjusted_score(result)
        candidate = dict(result)
        candidate["original_rank"] = result.get("rank")
        candidate["support_adjustment_weight"] = weight
        candidate["support_adjusted_score"] = adjusted_score
        simulated.append(candidate)
    simulated.sort(key=lambda item: (-item.get("support_adjusted_score", 0), item.get("original_rank") or 9999))
    for index, result in enumerate(simulated, 1):
        result["simulated_rank"] = index
    return simulated


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            item["_line"] = line_no
            records.append(item)
    return records


@lru_cache(maxsize=8)
def load_truth_items(path: str) -> List[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return []
    return _load_jsonl(path)


def find_truth_item(query: str, truth_items: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    normalized_query = normalize_text(query)
    for item in truth_items:
        if normalize_text(item.get("query", "")) == normalized_query:
            return item
    return None


def annotate_results(
    query: str,
    results: List[Dict[str, Any]],
    truth_path: str,
    mode: str = "annotate",
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Annotate results with truth-support signals.

    mode='annotate' keeps order intact. mode='rerank' applies conservative
    support-action weights after annotation.
    """
    truth_item = find_truth_item(query, load_truth_items(os.path.abspath(truth_path)))
    if not truth_item:
        return results

    limit = min(len(results), top_k or len(results))
    annotated = []
    for index, result in enumerate(results):
        if index >= limit:
            annotated.append(result)
            continue
        item = dict(result)
        support_signals = evaluate_result_support(truth_item, item)
        adjusted_score, weight = support_adjusted_score({**item, **support_signals})
        item["support_guard"] = {
            "truth_id": truth_item.get("id", ""),
            "truth_line": truth_item.get("_line"),
            "mode": mode,
            "original_rank": index + 1,
            "support_adjustment_weight": weight,
            "support_adjusted_score": adjusted_score,
        }
        item["support_signals"] = support_signals
        item["support_action"] = support_signals["support_action"]
        item["support_judgment"] = support_signals["support_judgment"]
        annotated.append(item)

    if mode == "rerank":
        head = annotated[:limit]
        tail = annotated[limit:]
        head.sort(key=lambda item: (-item.get("support_guard", {}).get("support_adjusted_score", 0), item.get("support_guard", {}).get("original_rank", 9999)))
        for index, item in enumerate(head, 1):
            item.setdefault("support_guard", {})["reranked_rank"] = index
        return head + tail

    return annotated
