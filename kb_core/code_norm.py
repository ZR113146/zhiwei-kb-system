# -*- coding: utf-8 -*-
"""标准编号归一化 —— 全项目唯一真源 (single source of truth)。

本模块只做纯字符串语法层面的标准编号处理, 零内部依赖 (仅 re),
可被 kb_core / pipeline / plan_writer 任意模块安全导入 (无循环导入风险)。

四个契约, 职责互不重叠:
  normalize_code(raw)   -> canonical: 前缀+编号, 去年份/去分隔符, /T·_T→T
                           'GB/T 50720-2011' / 'GB_T50720' -> 'GBT50720'
  extract_standard(raw) -> 从任意文本/文件名抽出结构化 dict
                           (standard_code / display_code / official_code /
                            standard_name / year)
  official_code(raw)    -> 人类可读官方形: 'GB_T 50720-2011' -> 'GB/T 50720-2011'

历史坑位 (回归测试 eval/code_norm_consistency.py 锚定, 勿再退化):
  - 下划线形式 'GB_T50720' 必须能解析 (入库文件名把 '/' 映射为 '_')
  - 年份必须先剥离再去横杠, 否则 '50720-2011' 会粘成 '507202011'
  - '/T' 形式不能丢 T (不能把 'GB/T50720' 归一成 'GB50720')
"""

import re

# 前缀显式枚举所有分隔符变体 (GB_T|GBT|GB, CJJ_T|..., DB\d{2}_T|...),
# 使下划线形式 (入库产物) 与斜杠/紧凑形式统一可解析。
_CODE_RE = re.compile(
    r"(TCECS|CECS|CJJ_T|CJJT|CJJ|CJ_T|CJT|CJ|JGJ_T|JGJT|JGJ|GB_T|GBT|GB|JTG_T|JTGT|JTG|JC_T|JCT|JC|DB\d{2}_T|DB\d{2}T|DB\d{2}|DB)"
    r"[\s_/-]*(?:T[\s_/-]*)?([A-Z]?\d+(?:\.\d+)?)"
    r"(?:[\s_-]*(19\d{2}|20\d{2}))?",
    re.IGNORECASE,
)


def normalize_code(raw):
    """规范形: 前缀+编号, 去年份, 去分隔符, /T·_T→T。"""
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
    """人类可读官方形, 同时保持 standard_code 文件安全。

    例: GB_T 50107-2010 -> GB/T 50107-2010; JGJ_T 23-2011 -> JGJ/T 23-2011。
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
    """从任意文本/文件名抽出结构化标准信息, 无匹配返回 None。"""
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
