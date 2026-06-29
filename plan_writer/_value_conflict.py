# -*- coding: utf-8 -*-
"""数值冲突检测 — 共享扫描骨架 (E5: verify/scan 公共部分抽取)。

verify.check_value_conflicts 与 scan_docx 的跨章数值冲突检测共享同一套
"逐段扫描 → 正则匹配 → 数值阈值过滤"流程。此模块只抽该公共骨架; 冲突判定、
单位归一化、主语消歧、输出格式等各自特有逻辑仍留在 verify/scan 各自处理。

设计: scan_hits() 返回原始命中 {key: [(page, val, text)]}, 调用方自行
做去重/归一/冲突判定。不改变任一方的对外行为。
"""

import re


def scan_hits(all_text, checks):
    """逐段扫描, 按 checks 配置匹配数值并做阈值过滤。

    Args:
        all_text: [(page_idx, text), ...]
        checks: {key: (pattern, min_val, max_val)}
                pattern 可以是 str 或已编译的 re.Pattern。

    Returns:
        {key: [(page_idx, val_str, text), ...]} — 通过阈值的原始命中。
        调用方负责后续去重/单位归一/主语消歧/冲突判定/输出格式。
    """
    compiled = {}
    for key, spec in checks.items():
        pat = spec[0]
        compiled[key] = pat if hasattr(pat, "search") else re.compile(pat)

    hits = {key: [] for key in checks}
    for page_idx, text in all_text:
        for key, (pat, min_val, max_val) in checks.items():
            m = compiled[key].search(text)
            if not m:
                continue
            val = m.group(1)
            try:
                fv = float(val)
            except ValueError:
                continue
            if fv < min_val or fv > max_val:
                continue
            hits[key].append((page_idx, val, text))
    return hits
