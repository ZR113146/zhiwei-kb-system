#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""resolver._common: KBResolver 共享前导层 (常量 + 无状态模块函数)。

原 kb_resolver_core.py 顶部 preamble (路径解析、编码归一化、术语映射展开等)
迁出至此, 供门面 kb_resolver_core 及各 mixin 子模块共同 import, 避免循环依赖。

行为契约: 与原 preamble 逐字一致, 唯一调整是路径锚点 —— 本文件位于
kb_core/resolver/, 比原 kb_core/ 深一层, 故 _KB_DIR 显式回退到 kb_core。
"""

import os, re, json, sys, math
from kb_core.standard_status import coverage as _status_coverage
from kb_core.standard_status import load_standard_status, status_for_code
from kb_core.standard_status import normalize_code as normalize_status_code

# ---- Path resolution (unified: kb.json) ----
# 本文件在 kb_core/resolver/_common.py, 上溯两级到项目根, 上溯一级到 kb_core。
# (原 preamble 在 kb_core/kb_resolver_core.py, _KB_DIR 即 kb_core; 此处保持一致语义。)
_RESOLVER_DIR = os.path.dirname(os.path.abspath(__file__))
_KB_DIR = os.path.dirname(_RESOLVER_DIR)        # kb_core/
_ROOT_DIR = os.path.dirname(_KB_DIR)            # project root

def _resolve_path(cfg_path):
    """Resolve relative path from kb.json to absolute path relative to project root."""
    if cfg_path.startswith("data") or cfg_path.startswith("pipeline") or cfg_path.startswith("plan_writer"):
        return os.path.join(_ROOT_DIR, cfg_path)
    return os.path.expanduser(cfg_path) if cfg_path.startswith("~") else cfg_path

def _load_paths():
    cfg_path = os.path.join(_KB_DIR, 'kb.json')
    if os.path.exists(cfg_path):
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        paths = cfg['paths']
        kb_md = _resolve_path(paths.get('kb_md', 'data/index'))
        kb_json = _resolve_path(paths.get('kb_json', 'data/kb_json'))
        return (
            _resolve_path(paths.get('standards_index', '')),
            kb_md,
            kb_json,
            os.path.join(kb_json, 'kb_search_index.json')
        )
    # Fallback
    kb_md = os.path.join(_ROOT_DIR, 'data', 'index')
    kb_json = os.path.join(_ROOT_DIR, 'data', 'kb_json')
    return ('', kb_md, kb_json, os.path.join(kb_json, 'kb_search_index.json'))

INDEX_PATH, KB_MD_DIR, KB_JSON_DIR, SEARCH_INDEX = _load_paths()
DEFAULT_SEARCH_TUNING = {
    'score_threshold': 10.0,
    'legacy_score_multiplier': 1.5,
    'ppr_score_divisor': 40.0,
    'vector_boost_multiplier': 5.0,
    'authority_boost_step': 0.01,
    'authority_boost_max': 0.2,
    'superseded_penalty': 0.65,
    'abolished_penalty': 0.4,
    'rerank_enabled': False,
    'rerank_top_k': 30,
    'rerank_provider': 'none',
    'clause_refine': True,
}

def _load_search_tuning():
    tuning = dict(DEFAULT_SEARCH_TUNING)
    cfg_path = os.path.join(_KB_DIR, 'kb.json')
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        search_cfg = cfg.get('search', {})
        if 'clause_refine' in search_cfg:
            tuning['clause_refine'] = bool(search_cfg['clause_refine'])
        tuning_path = search_cfg.get('tuning', '')
        if tuning_path:
            tuning_path = _resolve_path(tuning_path)
            if os.path.exists(tuning_path):
                with open(tuning_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                tuning.update({k: v for k, v in loaded.items() if not k.startswith('_')})
                tuning['_path'] = tuning_path
    except (OSError, json.JSONDecodeError, TypeError):
        tuning['_path'] = ''
    return tuning
IMAGE_INDEX_PATH = os.path.join(KB_JSON_DIR, 'kb_image_index.json')  # v6.18 图片元数据索引
BM25_INDEX_PATH = os.path.join(KB_JSON_DIR, 'kb_body_bm25.json')  # v6.18 段落BM25索引
FEEDBACK_LOG = os.path.join(_ROOT_DIR, 'pipeline', 'kb_feedback.jsonl')
TITLE_ALIAS_MAP = {
    '建设用卵石碎石': ['建设用卵石、碎石', '建设用卵石，碎石'],
    '建设用卵石，碎石': ['建设用卵石、碎石'],
    '建设用卵石、碎石': ['建设用卵石，碎石'],
}



def _is_toc_entry(text):
    """判断提取的文本是否为目录摘要（短、含页码、多条目连续）"""
    if not text or len(text) < 50:
        return True  # 太短，可能是目录行
    lines = text.strip().split('\n')
    if len(lines) < 3:
        return False
    # 目录特征：多行包含"…… 页码"或"数字 数字"结尾
    toc_lines = 0
    for line in lines[:5]:
        if re.search(r'……\s*\d+', line) or re.search(r'\d+\.\d+\s+\S{2,20}\s+\d{1,3}\s*$', line):
            toc_lines += 1
    return toc_lines >= 2  # 连续2行TOC特征 → 判定为目录


# ---- Code normalization ----
def normalize_code(raw):
    """Canonical form: prefix+number, no year, no separators.
    Key fix: strip trailing year (19xx/20xx) BEFORE removing dashes,
    so '50720-2011' → '50720' not '507202011'.
    GB_T→GBT, /T→T, JGJ-59→JGJ59."""
    c = raw.strip().replace(' ', '')
    if not c:
        return c
    # Strip trailing year before removing dashes (v8.0: prevents number+year merge)
    c = re.sub(r'[-](?:19|20)\d{2}$', '', c)
    c = c.replace('-', '')
    c = c.replace('/T', 'T').replace('_T', 'T')
    return c


def extract_code(text):
    """Extract first standard code from any text. Supports: GB/JGJ/CJJ/CECS/CJ/DB/JTG/TCECS + optional DB region + /T + fullwidth slash + underscore separator"""
    m = re.search(
        r'((?:GB|JGJ|CJJ|CECS|CJ|DB|JTG|TCECS)(?:\d+)?[\s_]*[/／]?[\s_]*T?[\s_]*[-]?[\s_]*\d+[\.-]\d+(?:-\d+)?)',
        text
    )
    if m:
        return normalize_code(m.group())  # normalize_code handles year/dash stripping
    return None


# ---- 编码结构化归一化 (v6.11) ----
# 语法定义:
#   Code = Prefix [T] Number ["-" Year]
#   Prefix = "GB" | "JGJ" | "CJJ" | "CECS" | "CJ" | "DB" Digit{2} | "JTG" | "TCECS"
#   T      = "/T" | "/T" | "T"
#   Number = Digit+ ["." Digit+]
#   Year   = Digit{4} (以19/20开头)

_STANDARD_PREFIXES = ['TCECS', 'CECS', 'CJJT', 'CJJ', 'JGJT', 'JGJ',
                       'GBT', 'GB', 'CJT', 'CJ', 'JTG',
                       'DB']  # DB 后需跟2位数字, 长前缀优先匹配

# 共通前缀 alternation: 路由判定/术语展开/权威性加成共用同一集合, 避免各处遗漏
# (CJ/CJT/CJJT/JGJT 等)。长前缀在前以保证正确回溯匹配。
_CODE_PREFIX_ALT = 'TCECS|CECS|CJJT|CJJ|JGJT|JGJ|GBT|GB|CJT|CJ|JTG|DB'

_PREFIX_PATTERN = re.compile(
    r'^(TCECS|CECS|CJJT|CJJ|JGJT|JGJ|GBT|GB|CJT|CJ|JTG|DB\d{2})',
    re.IGNORECASE
)

_CODE_TOKEN_RE = re.compile(
    r'^(TCECS|CECS|CJJT|CJJ|JGJT|JGJ|GBT|GB|CJT|CJ|JTG|DB\d{2})'  # prefix
    r'[\s/\-]*/?T?'                                              # 可选 /T
    r'[\s\-]*'                                                    # 分隔符
    r'(\d+(?:\.\d+)?)'                                           # number (含可选点号)
    r'(?:[\s\-]*(\d{4}))?'                                       # 可选年份
    , re.IGNORECASE
)


def parse_standard_code(token):
    """将字符串解析为结构化编码表示。

    Args:
        token: 任意字符串，如 "CJJ82", "GB 50204-2015", "JGJ-59-2011", "GB/T50107"

    Returns:
        None 如果 token 不是有效的标准编码格式
        dict {prefix, number, year, is_rec} 如果解析成功
          - prefix: 大写规范化前缀 (如 "CJJ", "JGJ", "DB32")
          - number: 编号字符串 (如 "82", "50204", "10801.1")
          - year:   年份字符串或 None (如 "2015")
          - is_rec: bool, 是否为推荐标准 (含 /T 标记)

    设计原则:
      1. 语法驱动——只接受符合标准编码语法的 token
      2. 前缀必须来自已知集合 (防止 EPS/LED 等误识别)
      3. DB 前缀后必须跟 2 位数字 (DB32, DB11)
      4. 编号至少 1 位, 年份必须以 19/20 开头
    """
    if not token or not isinstance(token, str):
        return None
    token = token.strip()
    if len(token) < 3:
        return None

    m = _CODE_TOKEN_RE.match(token)
    if not m:
        return None

    prefix = m.group(1).upper()
    number = m.group(2)
    year = m.group(3) if m.group(3) else None

    # DB 前缀验证: 必须恰好 2 位区域号
    if prefix.startswith('DB') and not re.match(r'^DB\d{2}$', prefix, re.IGNORECASE):
        return None

    # 年份验证: 必须以 19 或 20 开头
    if year and not re.match(r'^(19|20)', year):
        return None

    # 检测 /T 标记
    is_rec = bool(re.search(r'/?T', token[:m.end()], re.IGNORECASE))

    # 编号合理性: 不能太短 (至少 1 位) 且不能太长 (>10位)
    num_digits = number.replace('.', '')
    if len(num_digits) < 1 or len(num_digits) > 10:
        return None

    return {
        'prefix': prefix,
        'number': number,
        'year': year,
        'is_rec': is_rec,
    }


def canonicalize_code(parsed):
    """将解析后的结构化编码转为规范形式。

    规范形式 = prefix + number (去除 T 标记、年份、所有分隔符)

    Args:
        parsed: parse_standard_code() 的返回结果

    Returns:
        规范形式字符串，如 "GB50204", "CJJ82", "JGJ59", "GBT10801.1"
    """
    return parsed['prefix'] + parsed['number']


def normalize_code_token(token):
    """查询关键词归一化: 返回应追加到搜索词列表中的额外匹配形式。

    对于标准编码: 返回 [canonical, spaced_variant]
    对于非编码:   返回 []  (不做修改)

    追加而非替换——原始查询词保留, 归一化形式作为额外匹配通道。

    Args:
        token: 单个查询词

    Returns:
        list of str: 追加的匹配形式 (可能为空)
    """
    parsed = parse_standard_code(token)
    if not parsed:
        return []

    extras = []
    canonical = canonicalize_code(parsed)
    extras.append(canonical)

    # 有空格形式: prefix + 空格 + number, 用于匹配文件名的原始格式
    spaced = parsed['prefix'] + ' ' + parsed['number']
    if spaced.lower() != token.lower():
        extras.append(spaced)

    return extras


# ── 术语映射表 (v6.14) ──
# 路径锚到 contracts/ (与 kb.json 的 kb_term_map 值一致)。_common 是 resolver 底层,
# 不能 import kb(会成环), 故用 _ROOT_DIR 直接拼 contracts/ 而非走 load_config。
_TERM_MAP = None
_TERM_MAP_PATH = os.path.join(_ROOT_DIR, 'contracts', 'term_map.json')


def _load_term_map():
    global _TERM_MAP
    if _TERM_MAP is not None:
        return _TERM_MAP
    if os.path.exists(_TERM_MAP_PATH):
        with open(_TERM_MAP_PATH, 'r', encoding='utf-8') as f:
            _TERM_MAP = json.load(f)
    else:
        _TERM_MAP = {}
    return _TERM_MAP


def _expand_term_map(kw_list):
    """双向匹配术语映射表, 返回应追加到搜索词列表的领域同义词。

    匹配规则:
      1. 键命中: query词是映射表的一个键 → 展开该键所有值
      2. 值命中: query词出现在某个键的展开值中 → 展开该键所有值
    去重: 已存在于 kw_list 的词不重复追加。
    """
    term_map = _load_term_map()
    if not term_map:
        return []

    extras = []
    seen = set(k.lower() for k in kw_list)

    for kw in kw_list:
        # 子串匹配仅在自然语言查询中激活; 精确查询(含规范编号/标准名)不展开
        is_precise = bool(re.search(r'(?:' + _CODE_PREFIX_ALT + r')[\sT/\d]', kw) or
                         kw.endswith('规范') or kw.endswith('规程') or kw.endswith('标准'))
        use_substring = len(kw) <= 12 and not is_precise

        # 规则1: 键命中 (精确或子串)
        matched_key = None
        for key in term_map:
            if (key == kw) or (use_substring and key in kw):
                matched_key = key
                break
        if matched_key:
            for v in term_map[matched_key]:
                if v.lower() not in seen:
                    extras.append(v)
                    seen.add(v.lower())
            continue

        # 规则2: 值子串命中
        if use_substring:
            for key, vals in term_map.items():
                for v in vals:
                    if len(v) >= 2 and v in kw:
                        for v2 in vals:
                            if v2.lower() not in seen:
                                extras.append(v2)
                                seen.add(v2.lower())
                        break

    return extras



# ---- Index ----

# ---- v3 术语映射表 (专业分组 + 参数维度) ----
_TERM_MAP_V3_PATH = os.path.join(_ROOT_DIR, 'contracts', 'term_map_v3.json')
_TERM_MAP_V3 = None
_GNAME_TO_G = None

def _load_term_map_v3():
    global _TERM_MAP_V3, _GNAME_TO_G
    if _TERM_MAP_V3 is not None:
        return _TERM_MAP_V3, _GNAME_TO_G
    if os.path.exists(_TERM_MAP_V3_PATH):
        with open(_TERM_MAP_V3_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _TERM_MAP_V3 = data['term_index']
        _GNAME_TO_G = {g['name']: g for g in data['groups']}
    else:
        _TERM_MAP_V3 = {}
        _GNAME_TO_G = {}
    return _TERM_MAP_V3, _GNAME_TO_G


def _expand_term_map_v3(kw_list):
    index, gname_to_g = _load_term_map_v3()
    if not index:
        return []

    full_query_lower = ' '.join(kw_list).lower()
    term_groups = {}

    for kw in kw_list:
        matched_terms = set()
        if kw in index:
            matched_terms.add(kw)
        if len(kw) <= 12:
            for idx_term in index:
                if len(idx_term) >= 2 and idx_term in kw and idx_term != kw:
                    matched_terms.add(idx_term)
        for mt in matched_terms:
            if mt not in term_groups:
                term_groups[mt] = index[mt]

    group_score = {}
    for term, gnames in term_groups.items():
        for gn in gnames:
            g = gname_to_g.get(gn, {})
            kw_matches = sum(1 for k in g.get('keywords', []) if k.lower() in full_query_lower)
            group_score[gn] = group_score.get(gn, 0) + kw_matches + 1

    if not group_score:
        return []

    selected = sorted(group_score.items(), key=lambda x: -x[1])
    best_score = selected[0][1]
    selected_groups = [gn for gn, s in selected if s >= best_score and s >= 1][:2]

    extra = []
    seen = set(k.lower() for k in kw_list)
    for gn in selected_groups:
        g = gname_to_g.get(gn, {})
        for t in g.get('keywords', []) + g.get('related', []):
            if t.lower() not in seen:
                extra.append(t)
                seen.add(t.lower())

    param_indicators = ['长', '宽', '高', '厚', '间距', '深度', '长度',
                        '宽度', '高度', '厚度', '直径', '面积', '温度', '压力',
                        '角度', '等级', '比', '率', '系数', '指标', '量', '时间']
    has_param = any(p in full_query_lower for p in param_indicators)

    if has_param:
        for gn in selected_groups:
            g = gname_to_g.get(gn, {})
            for p in g.get('params', []):
                if p.lower() not in seen:
                    extra.append(p)
                    seen.add(p.lower())

    return extra[:15]


def _parse_rerank_order(text):
    """从 LLM 输出解析 top-3 重排顺序, 返回 [i,j,k] (0-based, 互异) 或 None。

    优先匹配显式 'X>Y>Z' 模式 (deepseek 推理模型即便 text 块被截断,
    thinking 块里通常也已给出结论)。无显式模式时回退到首个连续 3 字母。
    """
    if not text:
        return None
    up = text.upper()
    m = re.search(r'([ABC])\s*>\s*([ABC])\s*>\s*([ABC])', up)
    chars = [m.group(1), m.group(2), m.group(3)] if m else [c for c in up if c in 'ABC'][:3]
    ranking = [ord(c) - 65 for c in chars]
    if len(ranking) == 3 and len(set(ranking)) == 3 and max(ranking) < 3:
        return ranking
    return None


# 显式 __all__: 含下划线名, 使门面 `from resolver._common import *` 能取到全部
# preamble 名字 (普通 import * 会跳过下划线开头的名字)。external importers
# (kb.py / kb_loader.py / kb_current_state.py / server.py) 依赖其中若干公开名。
__all__ = [
    # standard_status re-exports (原 preamble 也 import 了它们, 保持可见)
    '_status_coverage', 'load_standard_status', 'status_for_code', 'normalize_status_code',
    # 路径 / 常量
    '_RESOLVER_DIR', '_KB_DIR', '_ROOT_DIR',
    'INDEX_PATH', 'KB_MD_DIR', 'KB_JSON_DIR', 'SEARCH_INDEX',
    'DEFAULT_SEARCH_TUNING', 'IMAGE_INDEX_PATH', 'BM25_INDEX_PATH', 'FEEDBACK_LOG',
    'TITLE_ALIAS_MAP',
    '_STANDARD_PREFIXES', '_CODE_PREFIX_ALT', '_PREFIX_PATTERN', '_CODE_TOKEN_RE',
    '_TERM_MAP', '_TERM_MAP_PATH', '_TERM_MAP_V3', '_TERM_MAP_V3_PATH', '_GNAME_TO_G',
    # 函数
    '_resolve_path', '_load_paths', '_load_search_tuning', '_is_toc_entry',
    'normalize_code', 'extract_code', 'parse_standard_code', 'canonicalize_code',
    'normalize_code_token', '_load_term_map', '_expand_term_map',
    '_load_term_map_v3', '_expand_term_map_v3', '_parse_rerank_order',
]
