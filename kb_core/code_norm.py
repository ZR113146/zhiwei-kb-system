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
    """规范形: 前缀+编号, 去年份, 去分隔符, /T·_T→T。

    v2 切换 (2026-07): 优先用分层解析器 _normalize_v2 (修了 v1 不认的 RISN /
    T-CECS 前缀等), v2 返空时回退 v1 单正则 (保护存量, 单调改进不回退)。
    切换经黄金真相表外部锚定子集 (samr evidence 4 条) + 存量 126 有码零变化
    双重验证; 回滚 = 还原此函数体为纯 v1 (git revert)。"""
    if not raw:
        return ""
    v2_result = _normalize_v2(raw)
    if v2_result:
        return v2_result
    # v1 回退 (v2 未识别的输入)
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


def normalize_code_with_year(raw):
    """归一码保留年份, 形如 GBT50720-2011。用于入库去重 (同号不同年版视为不同标准)。
    与 normalize_code 共享 _CODE_RE, 仅把年份拼回 — 单一真源, 避免入库侧自写正则漂移。"""
    if not raw:
        return ""
    text = str(raw).upper().replace("／", "/")
    text = re.sub(r"\s+", " ", text).strip()
    match = _CODE_RE.search(text)
    if not match:
        return ""
    code = normalize_code(match.group(0))
    if not code:
        return ""
    _prefix, _number, year = match.groups()
    return f"{code}-{year}" if year else code


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


# ============================================================================
# v2 — 分层解析器 (与 v1 并存, 不替换; 守护网双轨比对后再切换)。
# 设计目标: 把"推荐性 T"独立成 token, 族规则显式建模 (RISN/T-CECS/DB省码 ),
#           杜绝单正则补丁越补越脆。当前用于 eval/code_norm_consistency 双轨验证,
#           尚未被 normalize_code 调用 (切换在第3步, 由守护证明 v2 修裂≥1且回退0)。
# ============================================================================

# 族表: 前缀识别 (含 v1 漏的 RISN 与 T-前缀写法)。
#   写法变体按优先级: 长/具体的在前 (避免 TCECS 被 CECS 抢匹配)。
#   推荐(T)族: 写成 <PREFIX>T 的归一后缀; T 可来自 /T/_T/末尾T/T-前缀。
#   DB 族: 含 2 位省码, 写法可为 DB<省><标> (粘写) 或 DB<省>/T <标> (分割)。
#   RISN 族: 中国建筑标准设计研究院 (建筑标准设计), 形如 RISN-TG026 / RISN-TG<号>。
_FAMILY_RE = re.compile(
    r"(TCECS|CECS|CJJT|CJJ_T|CJJ|CJT|CJ_T|CJ|JGJT|JGJ_T|JGJ|GBT|GB_T|GB"
    r"|JTGT|JTG_T|JTG|JCT|JC_T|JC|DB\d{2}T|DB\d{2}_T|DB\d{2}|DB"
    r"|RISN)",
    re.IGNORECASE,
)
# 推荐性族 (有 /T 形式的): 归一时追加 T 到前缀。
_RECOMMENDED_FAMILIES = {"TCECS", "CECS", "CJJ", "CJ", "JGJ", "GB", "JTG", "JC", "DB", "RISN"}
# 但这些族本身已含 T (已是推荐形), 不再追加:
_ALREADY_T = {"TCECS", "CJJT", "CJT", "JGJT", "GBT", "JTGT", "JCT", "DBT"}


def _tokenize(raw):
    """把原始写法切成显式字段 {prefix, t, number, sub, year}。
    推荐性 T 独立成字段 (从 /T · _T · 末尾T · 或 RISN 默认推荐? 否) 解析, 不夹在前缀里。
    返回 None 表示无法识别为标准编号。"""
    if not raw:
        return None
    text = str(raw).upper().replace("／", "/")  # 全角斜杠归一
    # T-前缀写法: "T/CECS 1000" → prefix=CECS, t=True (推荐)。T/CECS 是 TCECS 的官方前缀形。
    m_tprefix = re.match(r"^T\s*/\s*(CECS|CJJT|CJJ|JGJ|GB|JTG|JC|DB)\s*[-_]?\s*(T?)\s*", text)
    if m_tprefix:
        return {"prefix": m_tprefix.group(1), "t": True,
                "number": _extract_number(text[m_tprefix.end():]),
                "year": _extract_year(text)}
    m = _FAMILY_RE.search(text)
    if not m:
        return None
    prefix = m.group(1).replace("_", "").replace("/", "")
    # RISN: 形如 RISN-TG026, number 应含 TG026 (从匹配点之后)
    if prefix == "RISN":
        rest = text[m.end():]
        mrisn = re.match(r"\s*-?\s*([A-Z]{1,2}\d+)", rest)
        number = mrisn.group(1) if mrisn else ""
        year = _extract_year(text)
        return {"prefix": "RISN", "t": False, "number": number, "sub": "", "year": year}
    # 末尾 T 已在前缀里 (CJJT/DB32T)? 拆出: CJJT→CJJ+T, DB32T→DB32+T (省码 DB32 保留)
    if prefix not in {"TCECS", "RISN"} and prefix.endswith("T"):
        stem = prefix[:-1]
        # stem 可能是裸族 (CJJ) 或 DB<省2位> (DB32) — 都视作"含T"拆出
        if stem in _RECOMMENDED_FAMILIES or re.fullmatch(r"DB\d{2}", stem) or re.fullmatch(r"DB", stem):
            t = True
            prefix = stem
    else:
        t = False
    rest = text[m.end():]
    # 推荐性 T 可随后续 /T 或 _T
    mt = re.match(r"\s*[/_-]?\s*T\b", rest)
    if mt:
        t = True
        rest = rest[mt.end():]
    number = _extract_number(rest)
    year = _extract_year(text)
    return {"prefix": prefix, "t": t, "number": number, "sub": "", "year": year}


def _extract_number(rest):
    rest = rest.lstrip(" /_-")
    m = re.match(r"([A-Z]?\d+(?:\.\d+)?)", rest)
    return m.group(1) if m else ""


def _extract_year(text):
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})\b", text)
    return m.group(1) if m else None


def _canonicalize(tok):
    """token → canonical (归一码, 去年份)。省码/推荐T 在此层组装。"""
    if not tok or not tok["number"]:
        return ""
    prefix = tok["prefix"]   # 形如 GB / CJJ / DB32 / RISN
    number = tok["number"]
    t = tok["t"]
    # ---- DB 地方标准族: prefix 可能是 DB (无省码粘写) 或 DB<省2位> ----
    # 依据 (samr dbba 采样 2026-07): 地方标准编号 = DB<省2位>(/T)? <标号>; 省码恒 2 位
    # (DB11京/DB31沪/DB32苏/DB44粤/DB42鄂...), 标号 4 位; 年份分隔符 - 或 — 不统一。
    # samr 抽样 DB32/T 5394, DB15/T 3700 等 6 条全部带 /T → 地方标准惯例为推荐性。
    # 故粘写形 DB323700 (用户省 /T) 默认按推荐性归一为 DB32T3700; 遇真强制性 DB (无 /T)
    # 需在 standard_status aliases 手动覆盖 (已知边界, 守护标注)。
    if prefix.startswith("DB"):
        prov = ""
        if re.fullmatch(r"DB\d{2}", prefix):
            prov = prefix[2:]            # DB32 → 省 32
            prefix = "DB"
        sticky = False
        if prefix == "DB" and not prov and number.isdigit() and len(number) >= 5 and "." not in number:
            # 粘写形 DB323700 (无省码分支): 推断省2位在 number 头
            prov = number[:2]
            number = number[2:]
            sticky = True
        # 地方标准惯例推荐性 (samr dbba 采样: DB32/T, DB15/T ... 全带 /T):
        # DB<省2位> 形式无显式 /T 标志时, 默认按推荐性加 T。遇真强制性 DB 需在
        # standard_status aliases 手动覆盖。覆盖粘写 + DB<省> 两种入口。
        if not t and prov:
            t = True
        return f"DB{prov}{'T' if t else ''}{number}"
    # ---- RISN 族: 形如 RISN-TG026 ----
    if prefix == "RISN":
        # number 已含 "TG026" 或 "TGxx" (见 _tokenize RISN 分支), 保留原始不剥前导0。
        if number:
            return f"RISN-{number}" if not number.startswith("RISN-") else number
        return "RISN"
    # ---- TCECS 族: 前缀本身是 T+CECS, canonical=TCECS (T 在前), 不走通用 t-后缀 ----
    if prefix == "TCECS":
        return f"TCECS{number}"
    # ---- 通用推荐族: prefix 是裸族 (CJJ/GB/JGJ/...), t=True → 拼回 T 在后 ----
    # 注: T/CECS 前缀写法 已在 _tokenize 把 prefix 设为 CECS + t=True, 但 TCECS 的 canonical
    # 是 prefix 在前(TCECS)而非后缀T。统一: 若是 CECS+t→用 TCECS 形式。
    if prefix == "CECS" and t:
        return f"TCECS{number}"
    if t:
        return f"{prefix}T{number}"
    return f"{prefix}{number}"


def _normalize_v2(raw):
    """v2 归一 (去年份)。与 v1 normalize_code 等价语义, 但分层实现。
    用于守护双轨比对, 未切换前不被生产代码调用。"""
    tok = _tokenize(raw)
    if not tok:
        return ""
    return _canonicalize(tok)


def _normalize_v2_with_year(raw):
    """v2 归一 (保年份), 对应 v1 normalize_code_with_year。"""
    c = _normalize_v2(raw)
    if not c:
        return ""
    tok = _tokenize(raw)
    return f"{c}-{tok['year']}" if tok["year"] else c
