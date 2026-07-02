# -*- coding: utf-8 -*-
"""标准编号归一化 —— 全项目唯一真源 (single source of truth)。

本模块只做纯字符串语法层面的标准编号处理, 零内部依赖 (仅 re),
可被 kb_core / pipeline / plan_writer 任意模块安全导入 (无循环导入风险)。

实现: 分层解析器 v2 — _tokenize 把原始写法切成显式字段 {prefix, t, number, year}
(推荐性 T 独立成 token, 不夹在前缀后缀里), _canonicalize 按族规则统一到 canonical。
族表 _FAMILY_RE 显式建模各前缀 (含 RISN / T-CECS 前缀 / DB 地方标准省码)。

四个契约, 职责互不重叠:
  normalize_code(raw)            -> canonical: 'GB/T 50720-2011' -> 'GBT50720'
  normalize_code_with_year(raw)  -> canonical+year: 'GBT50720-2011' (入库去重用)
  official_code(raw)             -> 官方形: 'GB_T 50720-2011' -> 'GB/T 50720-2011'
  extract_standard(raw)          -> 结构化 dict (standard_code/display_code/
                                     official_code/standard_name/year)

历史坑位 (回归测试 eval/code_norm_consistency.py 锚定, 勿再退化):
  - 下划线形式 'GB_T50720' 必须能解析 (入库文件名把 '/' 映射为 '_')
  - 年份必须先剥离再去横杠, 否则 '50720-2011' 会粘成 '507202011'
  - '/T' 形式不能丢 T (不能把 'GB/T50720' 归一成 'GB50720')
  - RISN 族 (RISN-TG026) / T-CECS 前缀 (T/CECS 1000) / DB 粘写 (DB323700) 必须识别
"""

import re
def normalize_code(raw):
    """规范形: 前缀+编号, 去年份, 去分隔符, /T·_T→T。分层解析器 v2 实现。
    例: 'GB/T 50720-2011' / 'GB_T50720' -> 'GBT50720'; 'DB323700' -> 'DB32T3700'。"""
    if not raw:
        return ""
    return _normalize_v2(raw)


def normalize_code_with_year(raw):
    """归一码保留年份, 形如 GBT50720-2011。用于入库去重 (同号不同年版视为不同标准)。"""
    if not raw:
        return ""
    return _normalize_v2_with_year(raw)


def official_code(raw):
    """人类可读官方形, 同时保持 standard_code 文件安全。

    例: GB_T 50107-2010 -> GB/T 50107-2010; JGJ_T 23-2011 -> JGJ/T 23-2011;
        DB32_T 3700-2019 -> DB32/T 3700-2019; T/CECS 1000 -> TCECS 1000;
        RISN-TG026-2020 -> RISN-TG026-2020。
    """
    tok = _tokenize(raw)
    if not tok or not tok["number"]:
        return ""
    prefix = tok["prefix"]
    t = tok["t"]
    number = tok["number"]
    year = tok["year"]
    suffix = f"-{year}" if year else ""
    # DB 地方标准: DB<省>/T <标号> (地方标准惯例推荐性, 与 _canonicalize 一致)
    if prefix.startswith("DB"):
        prov = prefix[2:] if re.fullmatch(r"DB\d{2}", prefix) else ""
        if not prov and number.isdigit() and len(number) >= 5 and "." not in number:
            prov = number[:2]; number = number[2:]
        if not t and prov:        # 无显式 /T 但有省码 → 默认推荐性 (与 _canonicalize 一致)
            t = True
        return f"DB{prov}{'/T' if t else ''} {number}{suffix}"
    # RISN: RISN-TG<号>
    if prefix == "RISN":
        return f"RISN-{number}{suffix}"
    # TCECS: T 在前 (TCECS 1000)
    if prefix == "TCECS" or (prefix == "CECS" and t):
        return f"TCECS {number}{suffix}"
    # 通用推荐族: <PREFIX>/T <标号> 或 <PREFIX> <标号>
    if t:
        return f"{prefix}/T {number}{suffix}"
    return f"{prefix} {number}{suffix}"


def extract_standard(raw):
    """从任意文本/文件名抽出结构化标准信息, 无匹配返回 None。

    用 _FAMILY_RE 定位编号 token (含 RISN / T-前缀写法), 归一化走 _tokenize/
    _canonicalize。standard_name 取编号 token 之后的文本 (去文件名后缀/seg 前缀)。
    """
    text = str(raw or "")
    # T/CECS 前缀写法: _FAMILY_RE 不直接认 "T/CECS", 先规范成 TCECS 形定位
    m_tprefix = re.match(r"^T\s*/\s*(CECS|CJJ|JGJ|GB|JTG|JC|DB)\b", text, re.IGNORECASE)
    if m_tprefix:
        m = m_tprefix
    else:
        m = _FAMILY_RE.search(text)
    if not m:
        return None
    # 编号 token = 从匹配起到 _extract_number 抓到的数字末尾
    tail = text[m.end():]
    num_m = re.match(r"\s*[/_-]?\s*T?\s*[/_-]?\s*([A-Z]?\d+(?:\.\d+)?)", tail, re.IGNORECASE)
    token_end = m.end() + (num_m.end() if num_m else 0)
    token = text[m.start():token_end]
    code = normalize_code(token)
    if not code:
        return None
    off = official_code(token)
    year = _extract_year(text)
    name = text[token_end:]
    name = re.sub(r"\.(json|md)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^[_\s-]+", "", name)
    name = re.sub(r"_p\d{4}-\d{4}$", "", name)
    name = name.strip() or text.strip()
    return {
        "standard_code": code,
        "display_code": token.strip(),
        "official_code": off,
        "standard_name": name,
        "year": int(year) if year else None,
    }


# ============================================================================
# 分层解析器: _tokenize (词法, T 独立成 token) + _canonicalize (族规则统一)。
# 设计: 推荐性 T 独立成 token (不夹在前缀后缀), 族规则显式建模 (RISN/T-CECS/
#       DB 省码), 杜绝单正则补丁越补越脆。全部 4 个生产函数走此实现。
# ============================================================================

# 族表: 前缀识别 (长/具体的在前, 避免 TCECS 被 CECS 抢匹配)。
#   推荐(T)族: 写成 <PREFIX>T 的归一后缀; T 可来自 /T/_T/末尾T/T-前缀。
#   DB 族: 含 2 位省码, 写法可为 DB<省><标> (粘写) 或 DB<省>/T <标> (分割)。
#   RISN 族: 中国建筑标准设计研究院 (建筑标准设计), 形如 RISN-TG026 / RISN-TG<号>。
_FAMILY_RE = re.compile(
    r"(TCECS|CECS|CJJT|CJJ_T|CJJ|CJT|CJ_T|CJ|JGJT|JGJ_T|JGJ|GBT|GB_T|GB"
    r"|JTGT|JTG_T|JTG|JCT|JC_T|JC|DB\d{2}T|DB\d{2}_T|DB\d{2}|DB"
    r"|RISN)",
    re.IGNORECASE,
)
# 推荐性族 (有 /T 形式): 归一时追加 T 到前缀 (在 _tokenize 拆末尾T时判定)。
_RECOMMENDED_FAMILIES = {"TCECS", "CECS", "CJJ", "CJ", "JGJ", "GB", "JTG", "JC", "DB", "RISN"}


def _tokenize(raw):
    """词法层: 把原始写法切成显式字段 {prefix, t, number, sub, year}。
    推荐性 T 独立成 t 字段 (从 /T · _T · 末尾T · T-前缀 解析), 不夹在前缀里。
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
