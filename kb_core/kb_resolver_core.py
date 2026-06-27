#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kb_resolver: shared knowledge base access layer for construction-plan-writer tools.

Consumed by: scan.py, verify.py, diff_docx.py
Data sources: kb.json paths (data/index/*.md, data/kb_json/kb_search_index.json)

Key insight: normalize standard codes once, use everywhere.
"""

import os, re, json, sys, math
from standard_status import coverage as _status_coverage
from standard_status import load_standard_status, status_for_code
from standard_status import normalize_code as normalize_status_code

# ---- Path resolution (unified: kb.json) ----
_KB_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_KB_DIR)  # project root

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
FEEDBACK_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pipeline', 'kb_feedback.jsonl')
TITLE_ALIAS_MAP = {
    '\u5efa\u8bbe\u7528\u5375\u77f3\u788e\u77f3': ['\u5efa\u8bbe\u7528\u5375\u77f3\u3001\u788e\u77f3', '\u5efa\u8bbe\u7528\u5375\u77f3\uff0c\u788e\u77f3'],
    '\u5efa\u8bbe\u7528\u5375\u77f3\uff0c\u788e\u77f3': ['\u5efa\u8bbe\u7528\u5375\u77f3\u3001\u788e\u77f3'],
    '\u5efa\u8bbe\u7528\u5375\u77f3\u3001\u788e\u77f3': ['\u5efa\u8bbe\u7528\u5375\u77f3\uff0c\u788e\u77f3'],
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
_TERM_MAP = None
_TERM_MAP_PATH = os.path.join(os.path.dirname(_KB_DIR),
                               'pipeline', 'kb_term_map.json')


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
_TERM_MAP_V3_PATH = os.path.join(os.path.dirname(_KB_DIR),
                                  'pipeline', 'kb_term_map_v3.json')
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


class KBResolver:
    def __init__(self):
        self.index = self._load_index()
        self.code_map = self._build_code_map()
        self.md_list = self._list_md_files()
        self.md_codes = self._build_md_code_map()
        self._search_cache = None      # lazy-loaded search index
        self._image_index = None       # lazy-loaded image index (v6.18)
        self._bm25_index = None        # lazy-loaded BM25 body index (v6.18)
        self._text_cache = {}          # filename → text (LRU, max 100)
        self._vector_searcher = None   # lazy-loaded LocalSemanticSearch
        self._cross_refs = None        # lazy-loaded cross-ref index (authority boost)
        self._authority_cache = {}     # standard_code → authority_score
        self._vector_boost_cache = {}  # query->boosts cache (v8.2 concurrency)
        self._search_result_cache = {}  # normalized query cache for repeated searches
        self._search_result_cache_order = []
        self._search_result_cache_size = 128
        self._standard_status_data = load_standard_status(KB_JSON_DIR)
        self._search_tuning = _load_search_tuning()

    def _load_index(self):
        if os.path.exists(INDEX_PATH):
            with open(INDEX_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _build_code_map(self):
        """Build standard_code → (index_key, clause_count) mapping"""
        m = {}
        for k, v in self.index.items():
            if k.startswith('_'):
                continue
            code = extract_code(k)
            if code:
                m[code] = {'key': k, 'clauses': len(v) if isinstance(v, list) else 0}
        return m

    def _list_md_files(self):
        if os.path.isdir(KB_MD_DIR):
            return [f for f in os.listdir(KB_MD_DIR) if f.endswith('.md')]
        return []

    def _build_md_code_map(self):
        """Build standard_code → MD_filename mapping (from filenames, most reliable source)"""
        m = {}
        for f in self.md_list:
            code = extract_code(f)
            if code:
                m[code] = f
        return m

    def _normalize_search_cache_key(self, keywords, max_results, project_standards, vector_weight, must, must_not, prefer):
        return json.dumps({
            'k': ' '.join((keywords or '').split()).strip().lower(),
            'm': int(max_results or 0),
            'p': sorted(project_standards) if project_standards else [],
            'v': round(float(vector_weight or 0), 3),
            'must': sorted(must) if must else [],
            'must_not': sorted(must_not) if must_not else [],
            'prefer': sorted(prefer) if prefer else [],
        }, ensure_ascii=False, sort_keys=True)

    def _cache_search_results(self, cache_key, results):
        annotated = self._annotate_search_results(results)
        if isinstance(results, list):
            results[:] = annotated
        else:
            results = annotated
        self._search_result_cache[cache_key] = [dict(r) for r in results]
        self._search_result_cache_order.append(cache_key)
        while len(self._search_result_cache_order) > self._search_result_cache_size:
            old_key = self._search_result_cache_order.pop(0)
            self._search_result_cache.pop(old_key, None)

    def _get_cached_search_results(self, cache_key):
        cached = self._search_result_cache.get(cache_key)
        if cached is None:
            return None
        return [dict(r) for r in cached]

    def _extract_result_code(self, result):
        for key in ('standard_code', 'code'):
            value = result.get(key) if isinstance(result, dict) else ''
            if value:
                code = normalize_status_code(value) or normalize_code(value)
                if code:
                    return code
        text = ' '.join(str(result.get(k, '')) for k in ('file', 'heading', 'text')) if isinstance(result, dict) else ''
        return extract_code(text) or normalize_status_code(text) or ''

    def _standard_status_for_code(self, code):
        return status_for_code(self._standard_status_data, code)

    def _code_candidates(self, standard_code):
        nc = normalize_code(standard_code)
        candidates = [nc] if nc else []
        aliases = (self._standard_status_data or {}).get('aliases', {})
        alias = aliases.get(normalize_status_code(standard_code) or nc)
        if alias and alias not in candidates:
            candidates.append(alias)
        if nc.startswith('GB') and not nc.startswith('GBT'):
            alt = nc.replace('GB', 'GBT', 1)
        elif nc.startswith('GBT'):
            alt = nc.replace('GBT', 'GB', 1)
        else:
            alt = None
        if alt and alt not in candidates:
            candidates.append(alt)
        return candidates

    def _standard_name_for_code(self, code):
        name = self.get_name(code) or ''
        if isinstance(name, (list, tuple)):
            return name[0] if name else ''
        return name

    def _official_code_for_code(self, code):
        status = self._standard_status_for_code(code)
        return status.get('official_code') or status.get('standard_code') or (normalize_status_code(code) or normalize_code(code))

    def _clause_content_flags(self, text):
        text = text or ''
        lower = text.lower()
        return {
            'has_table': '<table' in lower or '表 ' in text or '表格' in text,
            'has_formula': '$' in text or '公式' in text or '式(' in text or '式（' in text,
            'has_check_quantity': '检查数量' in text or '检查数量：' in text,
            'has_test_method': '检验方法' in text or '检验方法：' in text,
            'has_must_language': any(token in text for token in ['应', '不得', '不应', '必须', '严禁', '应符合']),
            'has_appendix_mark': '附录' in text or 'appendix' in lower,
            'has_deleted_clause': any(token in text for token in ['本条删除', '本条已删除', '删除']),
        }

    def _clause_candidate_summary(self, result):
        if not isinstance(result, dict):
            return {}
        code = self._extract_result_code(result)
        return {
            'standard_code': code,
            'official_code': self._official_code_for_code(code) if code else '',
            'standard_name': self._standard_name_for_code(code) if code else '',
            'heading': result.get('heading', ''),
            'source_file': result.get('file', ''),
            'clause_type': result.get('type') or result.get('clause_type') or 'unknown',
            'score': result.get('score', 0),
            'rank_source': result.get('rank_source') or result.get('_source') or '',
            'version_status': result.get('standard_status') or self._standard_status_for_code(code),
        }

    def _build_citation_object(self, data, audit_status=None, audit_messages=None):
        version_status = data.get('version_status') or {}
        status = version_status.get('status', 'unknown') if isinstance(version_status, dict) else 'unknown'
        messages = list(audit_messages or [])
        content_flags = data.get('content_flags') or {}
        if content_flags.get('has_deleted_clause') and 'clause_deleted' not in messages:
            messages.append('clause_deleted')
        if status in {'abolished', 'superseded'}:
            messages.append(f'version_status={status}')
        if data.get('error') and data.get('error') not in messages:
            messages.append(data.get('error'))
        if audit_status is None:
            if data.get('error') or status == 'abolished' or content_flags.get('has_deleted_clause'):
                audit_status = 'fail'
            elif messages or status in {'superseded', 'unknown'}:
                audit_status = 'warn'
            else:
                audit_status = 'pass'
        return {
            'standard_code': data.get('standard_code', ''),
            'official_code': data.get('official_code', ''),
            'standard_name': data.get('standard_name', ''),
            'clause_no': data.get('clause_no', ''),
            'clause_type': data.get('clause_type', 'unknown'),
            'quote_text': data.get('clause_text') or data.get('text', ''),
            'source_file': data.get('source_file', ''),
            'version_status': version_status if isinstance(version_status, dict) else {},
            'audit_status': audit_status,
            'audit_messages': messages,
            'confidence': data.get('confidence', ''),
            'source': data.get('source_file', ''),
        }

    def _annotate_search_results(self, results):
        if not results:
            return results
        annotated = []
        for result in results:
            if not isinstance(result, dict):
                annotated.append(result)
                continue
            code = self._extract_result_code(result)
            if code:
                result.setdefault('standard_code', code)
            version_status = self._standard_status_for_code(code)
            result['standard_status'] = version_status
            status_name = version_status.get('status', 'unknown')
            try:
                score_value = float(result.get('score', 0))
            except (TypeError, ValueError):
                score_value = 0.0
            if status_name == 'abolished':
                result['score'] = round(score_value * float(self._search_tuning.get('abolished_penalty', 0.4)), 4)
                result['version_penalty'] = 'abolished'
            elif status_name == 'superseded':
                result['score'] = round(score_value * float(self._search_tuning.get('superseded_penalty', 0.65)), 4)
                result['version_penalty'] = 'superseded'
            trace = result.get('_trace') if isinstance(result.get('_trace'), dict) else {}
            branch = trace.get('branch') or result.get('_source') or 'unknown'
            trace.setdefault('branch', branch)
            trace['rank_source'] = result.get('_source') or branch
            trace['final_score'] = result.get('score', 0)
            trace['standard_status'] = status_name
            result['_trace'] = trace
            result['rank_source'] = trace['rank_source']
            annotated.append(result)

        # 最终排序: 必须保住 T2 clause rerank 的决定 (否则它在这里被纯 score 排序静默推翻)。
        # 分层键: ①版本受罚项 (abolished/superseded) 始终殿后;
        #         ②同层内, 已 clause 精炼的结果 (带 _clause_sim) 按条款相关度优先 ——
        #           这些本就是 top-N 高分项, 精炼只是在文件内换到真正回答查询的条款;
        #         ③其余结果按 score 降序。clause_sim 与 score 不混排, 避免量纲错配。
        def _final_sort_key(item):
            if not isinstance(item, dict):
                return (1, 1, 0.0)
            penalized = 1 if item.get('version_penalty') else 0
            clause_sim = item.get('_clause_sim')
            if clause_sim is not None:
                return (penalized, 0, -float(clause_sim))
            try:
                score = float(item.get('score', 0))
            except (TypeError, ValueError):
                score = 0.0
            return (penalized, 1, -score)

        annotated.sort(key=_final_sort_key)
        return annotated

    def _classify_search_query(self, keywords):
        has_code = bool(re.search(r'(?:' + _CODE_PREFIX_ALT + r')[\sT/\d]', keywords or ''))
        is_std_name = (not has_code and any((keywords or '').endswith(word) for word in ['规范', '规程', '标准', '导则', '通则']))
        return has_code, is_std_name

    def _filter_standard_name_results(self, keywords, results):
        if any(word in keywords for word in
               ['怎么','如何','什么','哪些','多少','怎样','为何','为什么','怎么办','什么时候','要多高','要多长']):
            return results
        import jieba as _j2
        query_tokens = [token.strip() for token in _j2.lcut(keywords) if len(token.strip()) >= 2]
        if len(query_tokens) < 2:
            return results
        common_tokens = {'施工','规范','标准','规程','工程','技术','设计',
                         '质量','验收','安全','建筑','结构','材料','设备','安装'}
        filtered = []
        for result in results:
            fn_lower = result.get('file', '').lower()
            matched = [token for token in query_tokens if token in fn_lower]
            if len(matched) >= len(query_tokens) / 2:
                if any(token not in common_tokens for token in matched):
                    filtered.append(result)
        return filtered

    def _legacy_search_reason(self, has_code, is_std_name, must, must_not):
        reason = []
        if has_code: reason.append('code')
        if is_std_name: reason.append('std_name')
        if must: reason.append('must')
        if must_not: reason.append('must_not')
        return '+'.join(reason)

    def _merge_nl_candidates(self, ppr_candidates, legacy_results):
        for candidate in ppr_candidates:
            candidate['_raw_score'] = candidate.get('score', 0)
            candidate['score'] = candidate.get('score', 0) / float(self._search_tuning.get('ppr_score_divisor', 40.0))
        for candidate in legacy_results:
            candidate['_raw_score'] = candidate.get('score', 0)
            candidate['score'] = candidate.get('score', 0) * float(self._search_tuning.get('legacy_score_multiplier', 1.5))
        seen = {}
        for candidate in ppr_candidates:
            fname = candidate.get('file', '')
            if fname not in seen:
                seen[fname] = candidate
        for candidate in legacy_results:
            fname = candidate.get('file', '')
            if fname not in seen:
                candidate['_source'] = 'legacy'
                seen[fname] = candidate
            elif candidate.get('score', 0) > seen[fname].get('score', 0):
                candidate['_source'] = 'merged'
                seen[fname] = candidate
        return list(seen.values())

    def _build_nl_trace(self, ppr_candidates, legacy_results, candidates, skip_ppr, elapsed, extra_kws, term_extras):
        ppr_raw = max((candidate.get('_raw_score', 0) for candidate in ppr_candidates), default=0)
        legacy_raw = max((candidate.get('_raw_score', 0) for candidate in legacy_results), default=0)
        trace = {
            'branch': 'ppr+legacy',
            'ppr_candidates': len(ppr_candidates),
            'legacy_candidates': len(legacy_results),
            'merged_candidates': len(candidates),
            'raw_ppr_max': round(ppr_raw, 1),
            'raw_legacy_max': round(legacy_raw, 1),
            'ppr_skipped': skip_ppr,
            'elapsed_ms': round(elapsed, 0),
        }
        if extra_kws or term_extras:
            trace['expansion'] = {
                'code_normalized': extra_kws,
                'term_map': term_extras,
            }
        return trace

    def _ensure_search_cache_loaded(self):
        if self._search_cache is None:
            try:
                if os.path.exists(SEARCH_INDEX):
                    with open(SEARCH_INDEX, 'r', encoding='utf-8') as cache_file:
                        self._search_cache = json.load(cache_file)
            except Exception:
                pass

    def _adjust_nl_section_scores(self, results):
        for result in results:
            heading = re.sub(r'\s+', '', result.get('heading', ''))
            if re.match(r'^(?:[1-9]\d*\.?\s*)?(?:总\s*则|General|基本规定|一般要求|术语和符号|术语和定义|符号|范围|Scope|规范性引用文件|引用标准)$', heading):
                result['score'] = result.get('score', 0) * 0.01
            elif re.match(r'^(?:[1-9]\d*\.)+[1-9]\d*\s*(?:一般规定|一般要求|General)$', heading):
                result['score'] = result.get('score', 0) * 0.3
            elif re.search(r'\d+\.\d+\.\d+', heading):
                result['score'] = result.get('score', 0) * 1.3
        results.sort(key=lambda item: -item['score'])
        return results

    def _apply_prefer_tag_boost(self, results, prefer):
        prefer_tags = set(prefer) if prefer else set()
        if prefer_tags and results:
            for result in results:
                fpath = os.path.join(KB_MD_DIR, result.get('file', ''))
                if os.path.exists(fpath):
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as file_obj:
                            text = file_obj.read(2000)
                        match = re.search(r'^categories:\s*\[(.*?)\]', text, re.MULTILINE)
                        if match:
                            file_tags = set(tag.strip() for tag in match.group(1).split(','))
                            if prefer_tags & file_tags:
                                result['score'] = result.get('score', 0) * 1.15
                                result['tag_boost'] = True
                    except (KeyError, TypeError):
                        pass
        return results

    def _trim_intro_text(self, results):
        for result in results:
            result_text = result.get('text', '')
            if result_text and len(result_text) > 50:
                cut = re.search(r'(?:前\s*言|目\s*次|目\s*录|引\s*言)', result_text)
                if cut and cut.start() < 300:
                    result['text'] = result_text[:cut.start()]
        return results

    def _hydrate_nl_candidates(self, candidates):
        self._ensure_search_cache_loaded()
        index = (self._search_cache or {}).get('index', {})
        for candidate in candidates:
            if len(candidate.get('text', '')) >= 50:
                continue
            fname = candidate.get('file', '')
            if fname in index and index[fname]:
                section = index[fname][0]
                for alternate_section in index[fname][:10]:
                    heading = alternate_section.get('heading', '')
                    if re.search(r'(?:……\s*\d{1,4}|\s{2,}\d{1,4})\s*$', heading):
                        continue
                    heading_norm = re.sub(r'\s+', '', heading)
                    if re.match(r'^(?:[1-9]\d*\.?\s*)?(?:总\s*则|General|基本规定|一般要求|术语和符号|术语和定义|符号|范围|Scope|规范性引用文件|引用标准)$', heading_norm):
                        continue
                    if alternate_section.get('length', 0) >= 100:
                        section = alternate_section
                        break
                old_heading = candidate.get('heading', '')
                if not old_heading or old_heading.startswith('_seg') or len(old_heading) > 60:
                    candidate['heading'] = section.get('heading', '')[:80]
                fpath = os.path.join(KB_MD_DIR, fname)
                if os.path.exists(fpath):
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as file_obj:
                            body = file_obj.read()
                        pos, length = section.get('pos', 0), section.get('length', 2000)
                        candidate['text'] = body[pos:pos + min(length, 2000)]
                    except (KeyError, TypeError):
                        pass
        return candidates

    def _ensure_clause_index_loaded(self):
        if not hasattr(self, '_clause_index'):
            clause_index_path = os.path.join(KB_JSON_DIR, 'kb_clause_index.json')
            if os.path.exists(clause_index_path):
                with open(clause_index_path, 'r', encoding='utf-8') as file_obj:
                    self._clause_index = json.load(file_obj)
            else:
                self._clause_index = {'lookup': {}}
        return self._clause_index

    def _ensure_param_index_loaded(self):
        if not hasattr(self, '_param_index'):
            param_index_path = os.path.join(KB_JSON_DIR, 'kb_param_index.json')
            if os.path.exists(param_index_path):
                with open(param_index_path, 'r', encoding='utf-8') as file_obj:
                    self._param_index = json.load(file_obj)
            else:
                self._param_index = {'params': {}}
        return self._param_index

    def _parse_direct_clause_query(self, keywords):
        code_match = re.search(
            r'(TCECS|CECS|CJJ\s*/?\s*T?|JGJ\s*/?\s*T?|GB\s*/?\s*T?|CJ\s*/?\s*T?|JTG\s*/?\s*T?|DB\d{2}\s*/?\s*T?|DB\d{2}|DB)'
            r'[\s_/-]*([A-Z]?\d+(?:\.\d+)?)(?:[\s_-]*(?:19|20)\d{2})?',
            keywords,
            re.IGNORECASE,
        )
        clause_match = None
        standard_code = ''
        clause_tail_match = None
        clause_num = ''
        tail = ''
        tail_after_clause = ''
        if code_match:
            standard_code = code_match.group(0)
            tail = keywords[code_match.end():]
            clause_tail_match = re.search(r'(?:第\s*)?(\d+(?:\.\d+)+|[A-Z]|[IVXLCDM\u2160-\u217B]+)\s*[条款节章]?', tail, re.IGNORECASE)
            clause_num = clause_tail_match.group(1) if clause_tail_match else ''
            tail_after_clause = tail[clause_tail_match.end():].strip() if clause_tail_match else ''
            if not clause_num:
                number_text = code_match.group(2)
                if '.' in number_text:
                    clause_num = number_text
            if clause_num:
                clause_match = code_match
        return code_match, clause_match, standard_code, clause_tail_match, clause_num, tail, tail_after_clause

    def _param_index_result(self, param_name, entry):
        return {
            'file': entry.get('std_code', ''),
            'heading': '%s: %s = %s %s' % (
                entry.get('clause', '?'), param_name, entry.get('value', '?'),
                ('(%s)' % entry.get('condition', '')) if entry.get('condition') else ''
            ),
            'hits': 1,
            'score': 80.0,
            'text': entry.get('heading', ''),
            '_source': 'param_index'
        }

    def _reset_clause_metadata(self):
        self._last_type = None
        self._last_alternatives = []
        self._last_source_file = ''
        self._last_heading = ''
        self._last_match_method = ''
        self._last_clause_line = ''

    def _ensure_read_clause_search_index(self):
        if self._search_cache is None:
            if not os.path.exists(SEARCH_INDEX):
                self._rebuild_index_lite()
            else:
                with open(SEARCH_INDEX, 'r', encoding='utf-8') as file_obj:
                    self._search_cache = json.load(file_obj)
        return self._search_cache.get('index', {}) if self._search_cache else {}

    def _rank_clause_files(self, standard_code, clause_pattern, all_md):
        raw_parts = re.findall(r'\d+', standard_code)
        must_terms = [raw_parts[0] + '-' + raw_parts[1]] if len(raw_parts) >= 2 else []
        ranked = self.search(clause_pattern, max_results=5, must=must_terms) if must_terms else []
        seen = set()
        ranked_files = []
        for search_result in ranked:
            fname = search_result.get('file', '')
            if fname not in seen:
                seen.add(fname)
                ranked_files.append(fname)
        ordered_files = []
        for file_path in all_md:
            basename = os.path.basename(file_path)
            if basename in ranked_files:
                ordered_files.append(file_path)
        for file_path in all_md:
            if file_path not in ordered_files:
                ordered_files.append(file_path)
        return ordered_files, ranked, ranked_files

    def _assign_confidence(self, results):
        for result in results or []:
            if not isinstance(result, dict):
                continue
            score = result.get('score', 0)
            result['confidence'] = 'high' if score >= 60 else ('mid' if score >= 20 else 'low')
        return results

    def _set_trace(self, results, trace):
        for result in results or []:
            if isinstance(result, dict):
                result['_trace'] = trace
        return results

    def _apply_authority_boost(self, results, keywords=None):
        if not results:
            return results
        try:
            self._ensure_cross_refs()
            query_codes = set()
            if keywords:
                # 提取查询中的完整规范代码并归一化, 与 _cross_refs 的源代码同维度
                # (旧实现只取数字串, 与归一化全码 refs 永不相交 → ref_match 失效)
                for m in re.finditer(r'(?:' + _CODE_PREFIX_ALT + r')[\sT/]*\d+(?:\.\d+)?(?:-\d+)?', keywords):
                    qc = normalize_code(m.group(0))
                    if qc:
                        query_codes.add(qc)
            for result in results:
                if not isinstance(result, dict):
                    continue
                file_name = result.get('file', '')
                # 与 _authority_cache/_cross_refs 的键同维度 (normalize_code), 否则 /T 系标准永不命中
                standard_code = self._extract_code_from_filename(file_name)
                if not standard_code:
                    continue
                ref_count = self._authority_cache.get(standard_code, 0)
                if ref_count > 0:
                    boost = 1.0 + min(float(self._search_tuning.get('authority_boost_max', 0.2)), ref_count * float(self._search_tuning.get('authority_boost_step', 0.01)))
                    result['score'] = result.get('score', 0) * boost
                    result['ref_authority'] = ref_count
                if query_codes and standard_code in self._cross_refs:
                    refs = set(self._cross_refs.get(standard_code, []))
                    if refs & query_codes:
                        result['score'] = result.get('score', 0) * 1.15
                        result['ref_match'] = True
        except Exception:
            pass
        return results

    def _dedup_segmented_results(self, results):
        import re as _re
        dedup = {}
        for result in results or []:
            if not isinstance(result, dict):
                continue
            file_name = result.get('file', '')
            base = _re.sub(r'^_seg\d+_', '', file_name)
            base = _re.sub(r'_p\d+-\d+', '', base)
            if base not in dedup or result.get('score', 0) > dedup[base].get('score', 0):
                dedup[base] = result
        return list(dedup.values())

    def _prepare_legacy_keywords(self, keywords):
        kw_list = keywords.split()
        if len(kw_list) == 1 and len(kw_list[0]) > 6 and not re.search(r'[a-zA-Z0-9]', kw_list[0]):
            import jieba as _jieba
            tokens = [t.strip() for t in _jieba.lcut(keywords) if len(t.strip()) >= 2]
            if len(tokens) > 1:
                kw_list = tokens
        orig_kw_lower = [k.lower() for k in kw_list]
        extra_kws = []
        for kw in kw_list:
            extra_kws.extend(normalize_code_token(kw))
        if extra_kws:
            kw_list = kw_list + [k for k in extra_kws if k.lower() not in set(x.lower() for x in kw_list)]
        term_extras = _expand_term_map_v3(kw_list) or _expand_term_map(kw_list)
        if term_extras:
            kw_list = kw_list + [k for k in term_extras if k.lower() not in set(x.lower() for x in kw_list)]
        return kw_list, orig_kw_lower

    def _merge_legacy_bm25_results(self, results, keywords):
        try:
            bm25_results = self._bm25_search(keywords, max_results=30)
        except Exception:
            bm25_results = []
        bm25_file_set = set(result['file'] for result in results)
        for bm in bm25_results:
            if bm['file'] not in bm25_file_set:
                body_score = bm.get('bm25_score', 5.0) * 0.6
                if body_score >= 3.0:
                    results.append({
                        'file': bm['file'], 'heading': bm['heading'],
                        'hits': 1, 'score': body_score,
                        'text': f'[正文匹配: {bm["heading"]}]',
                        '_source': 'bm25_body'
                    })
            else:
                for result in results:
                    if result['file'] == bm['file'] and result.get('_source') != 'bm25_body':
                        result['score'] = result.get('score', 0) + bm.get('bm25_score', 0) * 0.2
                        break
        return results

    def _dedup_legacy_results(self, results):
        import re as _red
        dedup = {}
        for result in results:
            fname = result['file']
            base = _red.sub(r'^_seg\d+_', '', fname)
            base = _red.sub(r'_p\d+-\d+', '', base)
            if '(vector match)' in fname:
                base = fname
            if base not in dedup:
                dedup[base] = result
            elif result['score'] > dedup[base]['score']:
                dedup[base] = result
        results = list(dedup.values())
        results.sort(key=lambda x: -x['score'])
        return results

    def _trim_legacy_front_matter(self, results):
        for result in results:
            text = result.get('text', '')
            cut = re.search(r'(?:前\s*言|目\s*次|目\s*录|引\s*言)', text)
            if cut and cut.start() < min(500, len(text)):
                result['text'] = text[:cut.start()]
        return results

    def _load_legacy_file_text(self, fname):
        fpath = os.path.join(KB_MD_DIR, fname)
        if not os.path.exists(fpath):
            return None
        if fname in self._text_cache:
            return self._text_cache[fname]
        with open(fpath, 'r', encoding='utf-8', errors='replace') as file_obj:
            text = file_obj.read()
        if len(self._text_cache) >= 256:
            self._text_cache.pop(next(iter(self._text_cache)))
        self._text_cache[fname] = text
        return text

    def _passes_legacy_bool_filters(self, text, must_terms, not_terms):
        text_lower = None
        if must_terms:
            text_lower = text.lower()
            if not all(term in text_lower for term in must_terms):
                return False
        if not_terms:
            text_lower = text_lower if must_terms else text.lower()
            if any(term in text_lower for term in not_terms):
                return False
        return True

    # ---- Public API ----

    def exists(self, standard_code):
        """Check if standard exists — MD filenames primary, index secondary.
        Handles GBT/GB equivalence (GB50720 ≈ GBT50720)"""
        nc = normalize_code(standard_code)
        if nc in self.md_codes:
            return True
        if nc in self.code_map:
            return True
        # GBT/GB equivalence: also try alternate prefix
        alt = nc.replace('GB', 'GBT', 1) if nc.startswith('GB') and not nc.startswith('GBT') else nc.replace('GBT', 'GB', 1) if nc.startswith('GBT') else None
        if alt and (alt in self.md_codes or alt in self.code_map):
            return True
        # Fuzzy: check if any MD filename contains the code
        for f in self.md_list:
            fn = normalize_code(f.replace('.md', ''))
            if nc in fn or fn in nc:
                return True
            if alt and (alt in fn or fn in alt):
                return True
        return False

    def get_clause_count(self, standard_code):
        """Get number of indexed clauses for a standard"""
        for code_candidate in self._code_candidates(standard_code):
            entry = self.code_map.get(code_candidate, {})
            if entry:
                return entry.get('clauses', 0)
        return 0

    def _parse_name_from_filename(self, fname):
        """L1: Extract standard Chinese name from MD filename.
        Handles: 'GB 50209-2010 建筑地面工程施工质量验收规范.md'
                 '_seg3_GB 50666-2011 混凝土结构工程施工规范_p0201-0220.md'
                 'CJJT 287-2018  园林绿化养护标准.md'"""
        base = fname.replace('.md', '')
        # Strip _segN_ prefix
        base = re.sub(r'^_seg\d+_', '', base)
        # Remove trailing _pXXXX-XXXX segment marker
        base = re.sub(r'_p\d{4}-\d{4}$', '', base)
        # Split: code part ends at first non-code alpha boundary after the year
        # Pattern: CODE_PREFIX NUMBER[-.]NUMBER[-NUMBER] REST
        m = re.match(
            r'(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|JTG|TCECS)[\s/_]*T?[\s_]*\d+[\.-]\d+(?:-\d+)?)\s+(.+)',
            base, re.IGNORECASE
        )
        if m:
            name = m.group(1).strip()
            # Remove page range suffixes like _p0201-0251 that weren't caught above
            name = re.sub(r'[\s_]*_?p\d{4}[_-]\d{4}$', '', name).strip()
            return name if name else None
        return None

    _GENERIC_TITLES = {
        '中国工程建设协会标准', '中国工程建设标准化协会标准',
        '中华人民共和国国家标准', '中华人民共和国行业标准',
        '中华人民共和国住房和城乡建设部', '中华人民共和国国家质量监督检验检疫总局',
        '前言', '目次', '目录', '总则', '术语', '基本规定',
    }

    def _parse_name_from_body(self, md_path):
        """L2: Extract official standard name from document body.
        Sources (in priority order):
        1. YAML frontmatter title
        2. Standard declaration line: '标准编号 名称'
        3. First non-generic H1 heading
        4. Name following code on a separate line"""
        if not md_path or not os.path.exists(md_path):
            return None
        try:
            with open(md_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(8000)
        except Exception:
            return None

        # Source 1: YAML frontmatter title (highest priority)
        yaml_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if yaml_match:
            yaml = yaml_match.group(1)
            m = re.search(r'title:\s*["\']?([^"\'\n]{5,80})["\']?', yaml)
            if m:
                title = m.group(1).strip()
                # Strip standard code prefix
                title = re.sub(r'^(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?\s+', '', title)
                return title

        # Source 2: Standard declaration with code directly followed by name
        # Handles both "GB 50209-2010 建筑地面..." (with space) and "GB50204-2015混凝土..." (no space)
        m = re.search(
            r'(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s*'
            r'([\u4e00-\u9fff][\u4e00-\u9fff\s·]{3,50}?)(?:[\n\r]|"|\u201c|（|\()',
            content
        )
        if m:
            name = m.group(1).strip()
            if name not in self._GENERIC_TITLES:
                return name

        # Source 3: First non-generic H1 heading
        for m in re.finditer(r'^#\s+(.{3,80}?)(?:\n|$)', content, re.MULTILINE):
            h1 = m.group(1).strip()
            if h1 not in self._GENERIC_TITLES and \
               not re.match(r'^(前[言序]|目[次录]|总则|[0-9]+\.|附录|术语和|基本规定)', h1):
                return h1

        # Source 4: Code line followed by name on next line
        m = re.search(
            r'(?:GB|JGJ|CJJ|CECS|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?\s*\n'
            r'\s*#\s*([\u4e00-\u9fff][\u4e00-\u9fff\s·]{3,50})',
            content
        )
        if m:
            name = m.group(1).strip()
            if name not in self._GENERIC_TITLES:
                return name

        return None

    def _parse_name_from_content(self, standard_code):
        """L3: Deep search — read all segments, find most authoritative name.
        Used when L1/L2 fail or disagree."""
        nc = normalize_code(standard_code)
        md_files = self.find_all_md(standard_code)
        if not md_files:
            return None

        # Collect candidate names from all segments
        candidates = {}
        for md_path in md_files:
            if not md_path or not os.path.exists(md_path):
                continue
            try:
                with open(md_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(8000)
            except (IOError, OSError):
                continue

            # Find all occurrences of the code followed by a name
            for m in re.finditer(
                r'(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s+'
                r'([\u4e00-\u9fff][\u4e00-\u9fff\s·]{2,50}?)(?:[\n\r]|[（(]|"|\u201c)',
                content
            ):
                name = m.group(1).strip()
                # Filter garbage
                if len(name) >= 4 and not re.match(r'^[\s\d_\-\.,;]+$', name):
                    candidates[name] = candidates.get(name, 0) + 1

            # Also check for standard declaration patterns
            for m in re.finditer(
                r'(?:中华人民共和国国家标准|中华人民共和国行业标准|中国工程建设标准化协会标准)\s*\n'
                r'\s*((?:GB|JGJ|CJJ|CECS|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s+'
                r'([\u4e00-\u9fff][\u4e00-\u9fff\s·\-]{3,50})',
                content
            ):
                name = m.group(2).strip()
                if len(name) >= 4:
                    candidates[name] = candidates.get(name, 0) + 5  # Weight authoritative declarations higher

        if not candidates:
            return None

        # Return most frequent candidate
        return max(candidates, key=candidates.get)

    def get_name(self, standard_code):
        """Resolve standard code → official Chinese name. Three-layer fallback:
        L1: Parse MD filename (fast, 83 codes covered)
        L2: Extract from document body preamble (YAML→declaration→H1)
        L3: Deep content search across all segments (slow, last resort)

        Returns: (name: str, source_layer: int, confidence: str)
          confidence: 'high' (L1/L2 agree), 'medium' (single layer only), 'low' (L3 guess)
        """
        if not standard_code or not standard_code.strip():
            return None, 0, ''
        nc = normalize_code(standard_code)
        # GBT/GB equivalence: try alternate prefix

        l1_name = None
        l2_name = None

        # L1: from filename (try normalized code, status aliases, then GB/GBT alternate)
        for code_candidate in self._code_candidates(standard_code):
            if code_candidate in self.md_codes:
                l1_name = self._parse_name_from_filename(self.md_codes[code_candidate])
                if l1_name:
                    break
            # Fuzzy filename search
            for f in self.md_list:
                fn = normalize_code(f.replace('.md', ''))
                if code_candidate in fn or fn in code_candidate:
                    l1_name = self._parse_name_from_filename(f)
                    if l1_name:
                        break
            if l1_name:
                break

        # L2: from document body (find_md handles GBT/GB equivalence)
        md_path = self.find_md(standard_code)
        if md_path:
            l2_name = self._parse_name_from_body(md_path)

        # Determine confidence and return
        # Final name normalization
        def _clean_name(n):
            if not n:
                return n
            # Strip _segN_ prefix (segmented file artifact)
            n = re.sub(r'^_seg\d+_', '', n)
            # Strip leading code prefix (e.g. "GB 50204-2015混凝土..." or "JGJ-59-2011 建筑施工...")
            n = re.sub(r'^(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/\-]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s*', '', n)
            # Strip page range suffix
            n = re.sub(r'_p\d{4}[_-]\d{4}$', '', n)
            # Strip version year suffix like "（2025年版）"
            n = re.sub(r'[（(]\d{4}年版[）)]', '', n).strip()
            return n.strip()

        if l1_name and l2_name:
            def _norm(s):
                return s.replace(' ', '').replace('·', '').replace('-', '').replace('（2025年版）', '')
            cn1 = _clean_name(l1_name)
            cn2 = _clean_name(l2_name)
            if _norm(cn1) == _norm(cn2):
                return cn1, 1, 'high'
            elif cn1 in cn2 or cn2 in cn1:
                return cn2 if len(cn2) >= len(cn1) else cn1, 2, 'high'
            else:
                return cn2, 2, 'medium'  # Body is more authoritative
        elif l1_name:
            return _clean_name(l1_name), 1, 'medium'
        elif l2_name:
            return _clean_name(l2_name), 2, 'medium'

        # L3: deep search
        l3_name = self._parse_name_from_content(standard_code)
        if l3_name:
            return l3_name, 3, 'low'

        return None, 0, 'not_found'

    def find_md(self, standard_code):
        """Find MD file path for a standard code. Returns best match (prefer non-seg, or first seg)"""
        code_candidates = self._code_candidates(standard_code)
        for code_candidate in code_candidates:
            if code_candidate in self.md_codes:
                return os.path.join(KB_MD_DIR, self.md_codes[code_candidate])
        matches = []
        for f in self.md_list:
            fn = normalize_code(f.replace('.md', ''))
            if any(code_candidate in fn or fn in code_candidate for code_candidate in code_candidates):
                matches.append(os.path.join(KB_MD_DIR, f))
        return matches[0] if matches else None

    def find_all_md(self, standard_code):
        """Find ALL MD files for a standard (handles segmented files like _seg0, _seg1...)"""
        matches = []
        code_candidates = self._code_candidates(standard_code)
        for code_candidate in code_candidates:
            if code_candidate in self.md_codes:
                fp = os.path.join(KB_MD_DIR, self.md_codes[code_candidate])
                if fp not in matches:
                    matches.append(fp)
        for f in self.md_list:
            fn = normalize_code(f.replace('.md', ''))
            if any(code_candidate in fn or fn in code_candidate for code_candidate in code_candidates):
                fp = os.path.join(KB_MD_DIR, f)
                if fp not in matches:
                    matches.append(fp)
        status_code = normalize_status_code(standard_code)
        for f in self.md_list:
            fn = normalize_status_code(f.replace('.md', '')) or normalize_code(f.replace('.md', ''))
            if status_code and fn == status_code:
                fp = os.path.join(KB_MD_DIR, f)
                if fp not in matches:
                    matches.append(fp)
        return matches

    def _extract_clause_from_md_text(self, text, clause_num):
        if not text or not clause_num:
            return '', ''
        clause_re = re.compile(r'^#*\s*' + re.escape(clause_num) + r'(?![\d.])(?:\s|$|[（(])')
        lines = text.split('\n')
        start = None
        for index, line in enumerate(lines):
            if clause_re.search(line.strip()):
                start = index
                break
        if start is None:
            return '', ''
        extracted = []
        next_clause_re = re.compile(r'^#*\s*(\d+(?:\.\d+)+|[A-Z][A-Z0-9]*|[IVXLCDM\u2160-\u217B]+)(?![\d.])(?:\s|$|[（(])')
        for index in range(start, min(len(lines), start + 100)):
            line = lines[index]
            if index > start:
                match = next_clause_re.search(line.strip())
                if match and match.group(1) != clause_num:
                    break
            extracted.append(line)
        return '\n'.join(extracted).strip()[:3000], lines[start].strip()

    def _locate_clause_index(self, fname, text, clause_pattern, prefer_type, search_index, ranked, ranked_files, is_clause_number):
        """Locate the best clause index for numbered clause reads."""
        _TYPE_PRIORITY = {'normative': 0, 'commentary': 1, 'appendix': 2, 'reference': 3}

        def _sort_by_type(sections, prefer=None):
            if prefer == 'any':
                return list(sections)
            if prefer and prefer in _TYPE_PRIORITY:
                return sorted(sections, key=lambda s: (0 if s.get('type') == prefer else 1, _TYPE_PRIORITY.get(s.get('type', 'normative'), 0)))
            return sorted(sections, key=lambda s: _TYPE_PRIORITY.get(s.get('type', 'normative'), 0))

        def _has_clause_pattern(value):
            if not is_clause_number:
                return clause_pattern in value
            return bool(re.search(r'(?<![\d.])' + re.escape(clause_pattern) + r'(?![\d.])', value))

        def _find_clause_pattern(value):
            if not is_clause_number:
                return value.find(clause_pattern)
            match = re.search(r'(?<![\d.])' + re.escape(clause_pattern) + r'(?![\d.])', value)
            return match.start() if match else -1

        def _section_for_position(sections, pos):
            for sec in sections:
                start = sec.get('pos', 0)
                end = start + sec.get('length', 0)
                if start <= pos < end:
                    return sec
            return None

        idx = None
        if not is_clause_number:
            return idx

        if ranked and fname in ranked_files:
            for sr in ranked:
                if sr.get('file') == fname:
                    best_h = sr.get('heading', '')
                    if best_h:
                        sections = search_index.get(fname, [])
                        matches = [s for s in sections if s.get('heading', '') == best_h]
                        if matches:
                            sorted_matches = _sort_by_type(matches, prefer_type)
                            idx = sorted_matches[0]['pos']
                            self._last_type = sorted_matches[0].get('type', 'normative')
                            self._last_source_file = fname
                            self._last_heading = sorted_matches[0].get('heading', best_h)
                            self._last_match_method = 'ranked_heading'
                            if len(sorted_matches) > 1:
                                self._last_alternatives = [
                                    {'type': s.get('type', 'normative'), 'heading': s['heading']}
                                    for s in sorted_matches[1:]
                                ]
                            break
            if idx is not None and prefer_type and prefer_type != 'normative' and (self._last_type or 'normative') != prefer_type:
                si_secs = search_index.get(fname, [])
                target_secs = _sort_by_type(si_secs, prefer_type)
                for sec in target_secs:
                    seg = text[sec['pos']:sec['pos'] + sec['length']]
                    if _has_clause_pattern(seg):
                        idx = sec['pos']
                        self._last_type = prefer_type
                        self._last_alternatives = [{'type': 'normative', 'heading': '正文中有等价条款'}]
                        break

        if idx is not None and prefer_type and prefer_type != 'normative':
            sel_type = self._last_type or 'normative'
            if sel_type != prefer_type:
                sections = search_index.get(fname, [])
                target_secs = _sort_by_type(sections, prefer_type)
                for sec in target_secs:
                    seg = text[sec['pos']:sec['pos'] + sec['length']]
                    if _has_clause_pattern(seg):
                        idx = sec['pos']
                        self._last_type = prefer_type
                        break
            if self._last_type != prefer_type:
                idx = None
        elif idx is None:
            sections = search_index.get(fname, [])
            sections_sorted = _sort_by_type(sections, prefer_type)
            for sec in sections_sorted:
                h = sec.get('heading', '')
                if _has_clause_pattern(h) and not re.search(r'(……|\d{3,}$|^目)', h):
                    idx = sec['pos']
                    self._last_type = sec.get('type', 'normative')
                    self._last_source_file = fname
                    self._last_heading = h
                    self._last_match_method = 'index_heading'
                    break
        if idx is None:
            esc = re.escape(clause_pattern)
            if prefer_type and prefer_type != 'normative':
                ref_secs = search_index.get(fname, [])
                for sec in ref_secs:
                    if sec.get('type') == prefer_type:
                        seg = text[sec['pos']:sec['pos'] + sec['length']]
                        m = re.search(r'(?:^|\n)(\s*)' + esc + r'(\s)', seg, re.MULTILINE)
                        if m:
                            idx = sec['pos'] + m.start() + len(m.group(1))
                            self._last_type = prefer_type
                            self._last_source_file = fname
                            self._last_heading = sec.get('heading', '')
                            self._last_match_method = 'prefer_type_regex'
                            break
            else:
                m = re.search(r'(?:^|\n)(\s*)' + esc + r'(\s)', text, re.MULTILINE)
                if m:
                    idx = m.start() + len(m.group(1))
                    self._last_source_file = fname
                    self._last_heading = ''
                    sec = _section_for_position(search_index.get(fname, []), idx)
                    if sec:
                        self._last_type = sec.get('type', 'unknown')
                        self._last_heading = sec.get('heading', '')
                    self._last_match_method = 'regex'
        return idx

    def read_clause(self, standard_code, clause_pattern, prefer_type=None):
        """Read specific clause text from KB. Auto-resolves cross-references.
        clause_pattern: '4.4.2' or '表3' or '5.3.3'
        prefer_type: None(正文优先) | 'normative' | 'commentary' | 'appendix' | 'any'(返回首个)
        用 search 引擎定位最佳匹配文件/位置 → 文件精读。
        v6.18: 正文优先(normative) > 条文说明(commentary) > 附录(appendix)
        v6.18: _last_type 记录返回类型, _last_alternatives 记录备选版本"""
        # Reset metadata trackers
        self._reset_clause_metadata()

        all_md = self.find_all_md(standard_code)
        if not all_md:
            return None

        result = None
        is_clause_number = bool(re.match(r'^[\d.IVXLCDM\u2160-\u217B]+$', clause_pattern))

        def _has_clause_pattern(value):
            if not is_clause_number:
                return clause_pattern in value
            return bool(re.search(r'(?<![\d.])' + re.escape(clause_pattern) + r'(?![\d.])', value))

        def _find_clause_pattern(value):
            if not is_clause_number:
                return value.find(clause_pattern)
            match = re.search(r'(?<![\d.])' + re.escape(clause_pattern) + r'(?![\d.])', value)
            return match.start() if match else -1

        def _section_for_position(sections, pos):
            for sec in sections:
                start = sec.get('pos', 0)
                end = start + sec.get('length', 0)
                if start <= pos < end:
                    return sec
            return None
        ranked = []
        ranked_files = []
        # 用搜索引擎定位：heading_match×5 让条款正文排在目录摘要前面
        if is_clause_number:
            all_md, ranked, ranked_files = self._rank_clause_files(standard_code, clause_pattern, all_md)

        # 确保搜索索引已加载 (read_clause 可能跳过 search() 调用)
        search_index = self._ensure_read_clause_search_index()

        for md_path in all_md:
            try:
                with open(md_path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except FileNotFoundError:
                continue
            fname = os.path.basename(md_path)

            # 方式1: 条款号定位——优先搜索索引pos, 回退到regex
            if is_clause_number and not result:
                idx = self._locate_clause_index(fname, text, clause_pattern, prefer_type, search_index, ranked, ranked_files, is_clause_number)
                if idx is not None:
                    # v6.17: 从索引位置提取, 放宽边界防止子标题截断
                    suffix = text[idx:min(len(text), idx + 3000)]
                    lines = suffix.split('\n')
                    clause_line = None
                    for i, line in enumerate(lines):
                        if _has_clause_pattern(line):
                            clause_line = i
                            break
                    if clause_line is not None:
                        extracted = []
                        for i in range(clause_line, min(len(lines), clause_line + 80)):
                            line = lines[i]
                            if i > clause_line:
                                # v6.19: 遇到章级或子条款标题即停 (含#前缀)
                                m = re.match(r'^#*\s*(\d+(?:\.\d+)*|[IVXLCDM\u2160-\u217B]+)\s+\S', line)
                                if m:
                                    hdr = m.group(1)
                                    if '.' not in hdr and clause_pattern.startswith(hdr + '.'):
                                        continue
                                    if hdr != clause_pattern:
                                        break
                            extracted.append(line)
                        candidate = '\n'.join(extracted).strip()[:3000]
                        if not _is_toc_entry(candidate):
                            result = candidate
                            self._last_source_file = self._last_source_file or fname
                            self._last_heading = self._last_heading or lines[clause_line].strip()
                            self._last_clause_line = lines[clause_line].strip()
                            self._last_match_method = self._last_match_method or 'clause_extract'


            # 方式2: kb_search_index 精确定位（适用于非条款号模式如"表3"）
            if not result and os.path.exists(SEARCH_INDEX):
                try:
                    with open(SEARCH_INDEX, 'r', encoding='utf-8') as f:
                        si = json.load(f)
                    sections = si.get('index', {}).get(fname, [])
                    for sec in sections:
                        if _has_clause_pattern(sec.get('heading', '')):
                            candidate = text[sec['pos']:sec['pos']+sec['length']].strip()[:3000]
                            if _has_clause_pattern(candidate):
                                result = candidate
                                self._last_type = sec.get('type', 'unknown')
                                self._last_source_file = fname
                                self._last_heading = sec.get('heading', '')
                                self._last_match_method = 'index_section'
                                break
                except json.JSONDecodeError:
                    import logging
                    logging.warning(f'Search index corrupt — falling back to regex.')
                except (json.JSONDecodeError, IOError):
                    pass

            # 方式3: 正则/子串回退 (v6.18: 支持prefer_type)
            if not result:
                if prefer_type and prefer_type != 'normative':
                    # 在指定type分区内找条款号
                    ref_secs = search_index.get(fname, [])
                    for sec in ref_secs:
                        if sec.get('type') == prefer_type:
                            seg = text[sec['pos']:sec['pos'] + sec['length']]
                            rel_idx = _find_clause_pattern(seg)
                            idx = sec['pos'] + rel_idx if rel_idx >= 0 else -1
                            if idx >= 0:
                                result = text[max(0, idx-200):
                                              min(len(text), idx+2000)].strip()
                                self._last_type = prefer_type
                                self._last_source_file = fname
                                self._last_heading = sec.get('heading', '')
                                self._last_clause_line = next((
                                    line.strip() for line in result.split('\n') if _has_clause_pattern(line)
                                ), '')
                                self._last_match_method = 'prefer_type_substring'
                                break
                else:
                    idx = _find_clause_pattern(text)
                    if idx >= 0:
                        result = text[max(0, idx-200):min(len(text), idx+2000)].strip()
                        self._last_source_file = fname
                        self._last_heading = ''
                        sec = _section_for_position(search_index.get(fname, []), idx)
                        if sec:
                            self._last_type = sec.get('type', 'unknown')
                            self._last_heading = sec.get('heading', '')
                        self._last_clause_line = next((
                            line.strip() for line in result.split('\n') if _has_clause_pattern(line)
                        ), '')
                        self._last_match_method = 'substring'

            if result:
                break

        # Auto-resolve cross-references (1 level max)
        if result:
            resolved = self._try_resolve_crossref(result, standard_code)
            if resolved:
                self._last_type = self._last_type or 'normative'
                return resolved
        # 正则回退无type信息, 标记为unknown
        if result and self._last_type is None:
            self._last_type = 'unknown'
        return result

    def read_clause_full(self, standard_code, clause_pattern, prefer_type=None):
        """v6.18: 返回完整信息 dict — text + type + alternatives
        调用方可通过 alternatives 判断是否需要补充查条文说明。
        read_clause() 仍然返回纯文本, 向后兼容。
        """
        text = self.read_clause(standard_code, clause_pattern, prefer_type)
        if not text:
            raw_candidates = self.search(clause_pattern or standard_code, max_results=5, vector_weight=0) if clause_pattern else []
            candidates = [self._clause_candidate_summary(item) for item in raw_candidates]
            failure_reason = 'standard_not_found' if not self.exists(standard_code) else 'clause_not_found'
            data = {
                'standard_code': normalize_status_code(standard_code) or normalize_code(standard_code),
                'official_code': self._official_code_for_code(standard_code),
                'standard_name': self._standard_name_for_code(standard_code),
                'clause_no': clause_pattern or '',
                'clause_text': '',
                'text': '',
                'clause_type': 'unknown',
                'type': 'unknown',
                'source_file': '',
                'version_status': self._standard_status_for_code(standard_code),
                'confidence': 'missing',
                'alternatives': getattr(self, '_last_alternatives', []),
                'candidates': candidates,
                'failure_reason': failure_reason,
                'diagnostic': {
                    'standard_exists': self.exists(standard_code),
                    'candidate_count': len(candidates),
                    'prefer_type': prefer_type or '',
                    'match_method': '',
                },
                'error': failure_reason,
            }
            data['citation'] = self._build_citation_object(data)
            return data
        clause_type = self._last_type or 'unknown'
        source_file = getattr(self, '_last_source_file', '')
        if not source_file:
            md_path = self.find_md(standard_code)
            source_file = os.path.basename(md_path) if md_path else ''
        confidence = 'high' if clause_type == 'normative' else ('mid' if clause_type in ('commentary', 'appendix') else 'low')
        content_flags = self._clause_content_flags(text)
        data = {
            'standard_code': normalize_status_code(standard_code) or normalize_code(standard_code),
            'official_code': self._official_code_for_code(standard_code),
            'standard_name': self._standard_name_for_code(standard_code),
            'clause_no': clause_pattern or '',
            'clause_text': text,
            'text': text,
            'content_flags': content_flags,
            'clause_type': clause_type,
            'type': clause_type,
            'source_file': source_file,
            'source_heading': getattr(self, '_last_heading', ''),
            'matched_clause_line': getattr(self, '_last_clause_line', ''),
            'match_method': getattr(self, '_last_match_method', ''),
            'version_status': self._standard_status_for_code(standard_code),
            'confidence': confidence,
            'alternatives': getattr(self, '_last_alternatives', []),
            'failure_reason': '',
            'diagnostic': {
                'standard_exists': True,
                'candidate_count': 0,
                'prefer_type': prefer_type or '',
                'match_method': getattr(self, '_last_match_method', ''),
            },
            'error': '',
        }
        data['citation'] = self._build_citation_object(data)
        return data

    def _try_resolve_crossref(self, text, standard_code):
        """
        Auto-resolves cross-references ONLY when the clause text is essentially
        just a pointer (e.g. "应符合本规范第X.X.X条的规定"). Does NOT follow
        incidental references embedded within substantive clause content.
        """
        if not text:
            return None
        # Only follow if text is short AND matches exactly a cross-ref pattern
        # (prevents following "3.0.21" inside "按本规范第3.0.21条检查" within a real clause)
        m = re.search(
            r'(?:\u672c\u89c4\u8303|\u672c\u89c4\u7a0b|\u672c\u6807\u51c6)\u7b2c\s*([\d.]+)\s*\u6761',
            text
        )
        if m and len(text) < 80:
            # Short text with cross-ref ONLY → follow it
            target_clause = m.group(1)
            key = (normalize_code(standard_code), target_clause)
            visited = getattr(self, '_crossref_visited', set())
            if key in visited:
                return None
            self._crossref_visited = set(visited) | {key}
            try:
                target = self.read_clause(standard_code, target_clause)
            finally:
                self._crossref_visited = visited
            if target and len(target) > 80:
                return target

        return None

    def _extract_code_from_filename(self, fname):
        """Extract standard code from MD filename for project_standards matching.
        v6.18: 剥离尾部年份(19xx/20xx)防止 JGJ-59-2011 → JGJ592011 的粘合错误"""
        m = re.search(r'(GB\s*/?\s*T?|JGJ\s*T?|CJJ\s*T?|CECS|CJ\s*/?\s*T?|DB)\s*[-]?\s*\d+[\.-]\d+(?:-\d+)?', fname)
        if m:
            code = m.group()
            # 剥离尾部年份: JGJ-59-2011 → JGJ-59, GB50204-2015 → GB50204
            code = re.sub(r'[-](?:19|20)\d{2}$', '', code)
            return normalize_code(code)
        return None

    def _idf_rarity_boost(self, kw_lower):
        """Rarity heuristic per keyword — zero-memory, zero-precompute.
        Uses keyword properties instead of corpus statistics:
        - 3+ CJK chars with specific domain chars → specialized (1.5x)
        - Contains code pattern (GB/JGJ/etc) → rare (3.0x)
        - Short filler words → common (1.0x)
        Avoids precomputing 5.7M n-grams which costs 700MB."""
        # Rare technical term indicators
        rare_patterns = [
            r'\u9632\u78b1', r'\u6cdb\u78b1',  # 防碱/泛碱
            r'\u80cc\u6d82',  # 背涂
            r'\u78be\u52b1',  # 碾压
            r'\u6324\u5bc6',  # 挤密
            r'\u710a\u63a5', r'\u63a2\u4f24',  # 焊接/探伤
        ]
        specialized_indicators = [
            r'\u7cfb\u6570', r'\u5ea6',  # 系数/度 (measurement terms)
            r'\u504f\u5dee', r'\u68c0\u9a8c',  # 偏差/检验
            r'\u6df7\u51dd\u571f', r'\u780c\u4f53',  # 混凝土/砌体
        ]
        short_fillers = {'\u65bd\u5de5', '\u5de5\u7a0b', '\u8fdb\u884c', '\u91c7\u7528', '\u7b26\u5408', '\u4e0d\u5f97',
                        '\u5e94\u5f53', '\u5fc5\u987b', '\u4e25\u7981', '\u4e00\u822c', '\u4ee5\u4e0a', '\u4ee5\u4e0b'}

        boosts = {}
        for kw in kw_lower:
            if any(re.search(p, kw) for p in rare_patterns):
                boosts[kw] = 3.0
            elif re.match(r'^(?:GB|JGJ|CJJ|CECS|CJ/T?)\s*\d+', kw.upper()):
                boosts[kw] = 3.0
            elif len(kw) <= 2 and kw in short_fillers:
                boosts[kw] = 1.0
            elif any(re.search(p, kw) for p in specialized_indicators) or len(kw) >= 3:
                boosts[kw] = 1.5
            else:
                boosts[kw] = 1.0
        return boosts

    def _ensure_vector_searcher(self):
        """Lazy-load LocalSemanticSearch. Returns the searcher or None."""
        if self._vector_searcher is None:
            try:
                import os as _os, sys as _sys
                _scripts = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'pipeline')
                if _scripts not in _sys.path:
                    _sys.path.insert(0, _scripts)
                from kb_vector_search_local import LocalSemanticSearch
                self._vector_searcher = LocalSemanticSearch()
            except ImportError:
                return None
        return self._vector_searcher

    def _get_query_vector(self, query):
        """Embed query ONCE per query, cache the raw qvec for sharing across
        doc-level boosts + clause refinement/rerank. Returns np.ndarray or None."""
        if self._vector_boost_cache.get("query") == query and self._vector_boost_cache.get("qvec") is not None:
            return self._vector_boost_cache["qvec"]
        searcher = self._ensure_vector_searcher()
        if searcher is None:
            return None
        try:
            qvec = searcher.embed(query)
        except Exception:
            return None
        cache = self._vector_boost_cache if self._vector_boost_cache.get("query") == query else {"query": query}
        cache["qvec"] = qvec
        self._vector_boost_cache = cache
        return qvec

    def _get_vector_boosts(self, query, top_k=15):
        """Doc-level vector boosts {normalized_code: similarity}, sharing the
        per-query embedding. Only loads the index on first call.
        """
        # v8.2: per-query cache — 并发线程共享向量结果
        if self._vector_boost_cache.get("query") == query and "boosts" in self._vector_boost_cache:
            return self._vector_boost_cache["boosts"]
        qvec = self._get_query_vector(query)
        if qvec is None:
            self._vector_boost_cache = {"query": query, "boosts": {}}
            return {}
        searcher = self._ensure_vector_searcher()
        try:
            vec_results = searcher.search_with_qvec(qvec, top_k=top_k, min_similarity=0.4)
        except Exception:
            self._vector_boost_cache["query"] = query
            self._vector_boost_cache["boosts"] = {}
            return {}

        boosts = {}
        for r in vec_results:
            code = r.get('code', '')  # LocalSemanticSearch uses 'code' not 'standard_code'
            if code and code != 'unknown':
                # Normalize and keep best similarity per code
                nc = normalize_code(code)
                sim = r.get('similarity', 0)
                if nc not in boosts or sim > boosts[nc]:
                    boosts[nc] = sim
        self._vector_boost_cache["query"] = query
        self._vector_boost_cache["boosts"] = boosts
        return boosts

    def _ensure_clause_searcher(self):
        """Lazy-load the clause-level vector searcher. Returns it or None."""
        if not hasattr(self, '_clause_searcher'):
            self._clause_searcher = None
            try:
                from clause_vector_search import get_clause_searcher
                cs = get_clause_searcher()
                self._clause_searcher = cs if cs.available() else None
            except Exception:
                self._clause_searcher = None
        return self._clause_searcher

    def _clause_text_for(self, fname, heading):
        """Map a clause-vector hit (file, heading) → current clause text via
        search_index (pos/length). Returns (heading, text, pos) or (None,None,None)."""
        self._ensure_search_cache_loaded()
        index = (self._search_cache or {}).get('index', {})
        sections = index.get(fname, [])
        target = None
        for sec in sections:
            if sec.get('heading', '') == heading:
                target = sec
                break
        if target is None:
            return None, None, None
        pos = target.get('pos', 0)
        length = min(target.get('length', 2000), 2000)
        fpath = os.path.join(KB_MD_DIR, fname)
        text = ''
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as fobj:
                    body = fobj.read()
                text = body[pos:pos + length]
            except OSError:
                text = ''
        return heading, text, pos

    def _refine_clause_targets(self, results, query, qvec=None, top_n=5):
        """T1: 把命中文件里展示的"泛泛章节"替换为语义上回答查询的具体条款。

        对 top_n 个结果, 用 clause 向量在该文件内找最匹配条款 (正文优先于条文说明),
        覆盖 heading/text 并记录 _clause_sim。仅当 clause 命中比当前展示更相关时替换。
        无 qvec / 无索引 / 无命中 → 原样返回 (优雅降级)。
        """
        if not self._search_tuning.get('clause_refine', True):
            return results
        cs = self._ensure_clause_searcher()
        if cs is None:
            return results
        if qvec is None:
            qvec = self._get_query_vector(query)
        if qvec is None:
            return results

        for r in results[:top_n]:
            fname = r.get('file', '')
            if not fname:
                continue
            try:
                hits = cs.search_clauses(qvec, top_k=5, file_filter=fname, min_similarity=0.45)
            except Exception:
                continue
            if not hits:
                continue
            # 正文优先于条文说明: 先在 normative 里取最高, 没有再退 commentary
            normative = [h for h in hits if h.get('type') == 'normative']
            best = (normative or hits)[0]
            heading, text, pos = self._clause_text_for(fname, best['heading'])
            if not text or len(text) < 20:
                continue
            r['heading'] = heading[:80]
            r['text'] = text
            r['_clause_sim'] = best['similarity']
            r['_clause_type'] = best.get('type', 'normative')
            src = r.get('_source', '')
            if 'clause_refine' not in src:
                r['_source'] = (src + '+clause_refine') if src else 'clause_refine'
        return results

    @staticmethod
    def _rewrite_head_scores(reordered_head):
        """重排后保持 score 与新位置单调一致: 把窗口内原有 score 降序重新分配到新顺序。

        重排器 (clause / LLM) 按自己的维度决定顺序后, score 若不回写, 下游纯 score 排序
        与可信度 (依赖 score) 会与展示顺序矛盾。此处让排第一的拿窗口最高分, 依次递减,
        使 rank / score / confidence 三者同源。原始 score 存入 _pre_rerank_score 备查。"""
        pool = sorted((r.get('score', 0) for r in reordered_head), reverse=True)
        for new_pos, result in enumerate(reordered_head):
            if '_pre_rerank_score' not in result:
                result['_pre_rerank_score'] = result.get('score', 0)
            result['score'] = pool[new_pos]
        return reordered_head

    def _clause_rerank(self, results, top_k=3):
        """T2: 用 _clause_sim 对 top-k 做确定性本地重排 (与 DeepSeek rerank 并存,
        作为可靠常开底座)。只重排已带 _clause_sim 的结果, 其余保持原序。"""
        head = results[:top_k]
        if not any('_clause_sim' in r for r in head):
            return results
        tail = results[top_k:]
        # 稳定排序: 有 _clause_sim 的按相似度降序, 无的保持原相对位置殿后
        indexed = list(enumerate(head))
        indexed.sort(key=lambda it: (-(it[1].get('_clause_sim', -1.0)), it[0]))
        new_head = self._rewrite_head_scores([r for _, r in indexed])
        return new_head + tail

    def _ensure_cross_refs(self):
        if self._cross_refs is not None:
            return
        cr_path = os.path.join(KB_JSON_DIR, "kb_cross_refs.json")
        if os.path.exists(cr_path):
            with open(cr_path, "r", encoding="utf-8") as _crf:
                self._cross_refs = json.load(_crf).get("target_to_source", {})
        else:
            self._cross_refs = {}
        if self._cross_refs:
            normalized_refs = {}
            for code, sources in self._cross_refs.items():
                ncode = normalize_code(code)
                if not ncode:
                    continue
                bucket = normalized_refs.setdefault(ncode, set())
                for source in sources:
                    bucket.add(normalize_code(source) or source)
            self._cross_refs = {code: sorted(sources) for code, sources in normalized_refs.items()}
            if not self._authority_cache:
                for code, sources in self._cross_refs.items():
                    self._authority_cache[code] = len(sources)


    def _try_filename_title_lookup(self, keywords, max_results=10):
        """Fast path for exact standard/material names present in MD filenames."""
        query = ''.join((keywords or '').split())
        if len(query) < 4:
            return None
        question_words = (
            '\u600e\u4e48', '\u5982\u4f55', '\u4ec0\u4e48', '\u54ea\u4e9b', '\u591a\u5c11',
            '\u600e\u6837', '\u4e3a\u4f55', '\u4e3a\u4ec0\u4e48', '\u600e\u4e48\u529e', '\u4ec0\u4e48\u65f6\u5019'
        )
        question_words = tuple(w.encode('utf-8').decode('unicode_escape') for w in question_words)
        if any(w in keywords for w in question_words):
            return None
        if not re.search(r'[\u4e00-\u9fff]', keywords):
            return None
        aliases = [query]
        for alias, variants in TITLE_ALIAS_MAP.items():
            if alias in query:
                aliases.extend(variants)
        aliases = [''.join(a.split()).lower() for a in aliases]
        query_code = extract_code(keywords) or normalize_status_code(keywords)
        query_code = query_code.upper() if query_code else ''
        chinese_terms = [
            term for term in re.findall(r'[\u4e00-\u9fff]{4,}', keywords or '')
            if not any(word in term for word in question_words)
        ]

        hits = []
        search_dirs = [(KB_MD_DIR, self.md_list)]
        md_lib_dir = os.path.join(_ROOT_DIR, 'data', 'md_lib_v2')
        if os.path.isdir(md_lib_dir):
            search_dirs.append((md_lib_dir, [f for f in os.listdir(md_lib_dir) if f.endswith('.md')]))
        seen = set()
        for base_dir, filenames in search_dirs:
            for fname in filenames:
                if fname in seen:
                    continue
                compact = ''.join(fname.replace('.md', '').split()).lower()
                file_code = extract_code(fname) or ''
                alias_match = any(alias in compact for alias in aliases)
                code_title_match = bool(
                    query_code and file_code.upper() == query_code
                    and chinese_terms
                    and any(term in compact for term in chinese_terms)
                )
                if not alias_match and not code_title_match:
                    continue
                seen.add(fname)
                fpath = os.path.join(base_dir, fname)
                snippet = ''
                if os.path.exists(fpath):
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                            snippet = f.read(800)
                    except OSError:
                        snippet = ''
                hits.append({
                    'file': fname,
                    'heading': fname.replace('.md', ''),
                    'hits': 1,
                    'score': 140.0 if code_title_match else 120.0,
                    'text': snippet,
                    '_source': 'filename_title',
                })
                if len(hits) >= max_results:
                    break
            if len(hits) >= max_results:
                break
        return hits or None

    def _try_direct_lookup(self, keywords):
        """v6.23: 精确查询直通车 — 条款号/参数名直接定位, 返回条款原文或参数值
        匹配模式:
          1. 'GB50204 5.3' → 查 clause_index → 返回条款原文
          2. '保护层厚度' → 查 param_index → 返回参数=数值列表
        返回 None 表示未命中, 走常规搜索
        """
        # ── 模式1: 标准编号 + 条款号 ──
        _code_m, _clause_m, _standard_code, _clause_tail_m, _clause_num, _tail, _tail_after_clause = self._parse_direct_clause_query(keywords)
        if _code_m and not _clause_m and any(token in _tail for token in ('现行', '废止', '版本')):
            _md_path = self.find_md(_standard_code)
            if _md_path and os.path.exists(_md_path):
                try:
                    with open(_md_path, 'r', encoding='utf-8', errors='replace') as _f:
                        _snippet = _f.read(1200)
                except OSError:
                    _snippet = ''
                _status = self._standard_status_for_code(_standard_code)
                _heading = _status.get('standard_name') or os.path.basename(_md_path).replace('.md', '')
                return [{
                    'file': os.path.basename(_md_path),
                    'heading': _heading,
                    'standard_code': normalize_status_code(_standard_code) or normalize_code(_standard_code),
                    'hits': 1,
                    'score': 110.0,
                    'text': _snippet,
                    '_source': 'standard_status_direct',
                }]
        if _clause_m:
            _explicit_clause_query = bool(_clause_tail_m and _tail_after_clause)
            _code_candidates = self._code_candidates(_standard_code)
            _code_norms = [c.replace('-','').replace(' ','').replace('_','').upper() for c in _code_candidates if c]

            # Load clause index
            _clause_index = self._ensure_clause_index_loaded()
            _lookup = _clause_index.get('lookup', {})

            # Normalize both sides (strip year, dashes, spaces)
            _candidates = []
            for _key in _lookup:
                _knorm = _key.replace('-','').replace(' ','').replace('_','').upper()
                if any(_norm and _norm in _knorm for _norm in _code_norms) and _key.endswith(':' + _clause_num):
                    _candidates.append(_key)
            if not _candidates:
                # Fallback: code+num不含年份, 只查编号+条款
                for _key in _lookup:
                    _knorm = _key.replace('-','').replace(' ','').replace('_','').upper()
                    if any(_norm and _norm in _knorm for _norm in _code_norms) and (':' + _clause_num) in _key:
                        _candidates.append(_key)
            _standard_file_found = False
            if _candidates:
                _key = _candidates[0]
                _entry = _lookup[_key]
                _fname = _entry['fname']
                _fpath = os.path.join(KB_MD_DIR, _fname)
                if os.path.exists(_fpath):
                    with open(_fpath, 'r', encoding='utf-8', errors='replace') as _f:
                        _text = _f.read()
                    _raw = _text[_entry['pos']:_entry['pos'] +
                                  min(_entry.get('length', 3000), 3000)].strip()
                    # 章节导航页检测: 简短 + 含多条 "X.X 标题 NNN" 模式
                    _nav_lines = re.findall(
                        r'^\d+(?:\.\d+)+\s+.{2,30}\s+\d{2,4}\s*$',
                        _raw, re.MULTILINE
                    )
                    _is_nav = (len(_raw) < 500 and len(_nav_lines) >= 2)
                    if _is_nav and '.' not in str(_entry.get('number', '')):
                        # 章节级条目命中导航页 → 递进到第一个子条款
                        _num = str(_entry.get('number', ''))
                        _sub_keys = [k for k in _candidates
                                     if k.endswith(':' + _num + '.')
                                     or re.search(r':' + re.escape(_num) + r'\.\d+$', k)]
                        if _sub_keys:
                            _sub = _lookup.get(sorted(_sub_keys)[0])
                            if _sub and _sub.get('pos'):
                                _entry = _sub
                                _raw = _text[_entry['pos']:_entry['pos'] +
                                             min(_entry.get('length', 3000), 3000)].strip()
                    return [{
                        'file': _fname,
                        'heading': '%s %s' % (_entry.get('number', ''), _entry.get('title', '')),
                        'hits': 1, 'score': 100.0,
                        'text': _raw,
                        '_source': 'clause_index'
                    }]

            # Fallback 2: 直查条款索引
            _ci_index = self._clause_index.get('index', {})
            for _fname, _data in _ci_index.items():
                _sc = _data.get('std_code', '')
                _sc_norm = _sc.replace('-','').replace(' ','').replace('_','').upper()
                if not _code_norms or not any(_norm and _norm in _sc_norm for _norm in _code_norms):
                    continue
                _standard_file_found = True
                for _c in _data.get('clauses', []):
                    if _c['number'] == _clause_num:
                        _fpath = os.path.join(KB_MD_DIR, _fname)
                        if os.path.exists(_fpath):
                            with open(_fpath, 'r', encoding='utf-8', errors='replace') as _f:
                                _text = _f.read()
                            return [{
                                'file': _fname, 'heading': '%s %s' % (_c['number'], _c.get('title', '')),
                                'hits': 1, 'score': 100.0,
                                'text': _text[_c['pos']:_c['pos'] + min(_c.get('length', 0), 3000)].strip(),
                                '_source': 'clause_index'
                            }]
                # Fallback 3: 标准存在但无此条款 → 返回正文首页 (score=90)
                if _standard_file_found and _explicit_clause_query:
                    continue
                _fpath = os.path.join(KB_MD_DIR, _fname)
                if os.path.exists(_fpath):
                    with open(_fpath, 'r', encoding='utf-8', errors='replace') as _f:
                        _text = _f.read()
                    # 跳过前言/目录: 找第一个正文章节位置
                    _body_pos = 0
                    _toc_m = re.search(r'^#{1,3}\s+(?:目\s*次|目\s*录)\s*$',
                                       _text, re.MULTILINE)
                    _scan = _toc_m.end() if _toc_m else 0
                    for _pat in [r'^#{1,3}\s+\d+\s+总\s*则',
                                 r'^#{1,3}\s+基本规定',
                                 r'^#{1,3}\s+1\s+总\s*则']:
                        _bm = re.search(_pat, _text[_scan:], re.MULTILINE)
                        if _bm:
                            _body_pos = _scan + _bm.start()
                            break
                    _start = _body_pos if _body_pos > 0 else 0
                    return [{
                        'file': _fname, 'heading': _data.get('std_code', ''),
                        'hits': 1, 'score': 90.0,
                        'text': _text[_start:_start + 2000],
                        '_source': 'clause_index_fallback'
                    }]

        # ── 模式2: 参数名查询 ──
        if _clause_m:
            for _md_path in self.find_all_md(_standard_code):
                if not os.path.exists(_md_path):
                    continue
                try:
                    with open(_md_path, 'r', encoding='utf-8', errors='replace') as _f:
                        _text = _f.read()
                except OSError:
                    continue
                _raw, _heading = self._extract_clause_from_md_text(_text, _clause_num)
                if not _raw:
                    continue
                return [{
                    'file': os.path.basename(_md_path),
                    'heading': _heading,
                    'standard_code': normalize_status_code(_standard_code) or normalize_code(_standard_code),
                    'hits': 1,
                    'score': 105.0,
                    'text': _raw,
                    '_source': 'md_clause_direct',
                }]

        _param_index = self._ensure_param_index_loaded()
        _params = _param_index.get('params', {})

        for _pname, _entries in _params.items():
            if _pname in keywords:
                _results = []
                for _e in _entries[:5]:
                    _results.append(self._param_index_result(_pname, _e))
                if _results:
                    return _results
                break

        return None

    def _rebuild_index_lite(self):
        """索引损坏或缺失时自动重建 (v6.18: 含type标注+噪音过滤, 与正式索引一致)"""
        import re as _re
        # v6.18: 噪音过滤 (与 kb_search_index.py 同步)
        _FRONT_NOISE = {
            '前言','目次','目录','引言','公告','通知',
            '修订说明','编制说明','条文说明','中华人民共和国','发布',
            '住房城乡建设部','关于发布','施行日期','主编单位','批准部门',
            '编制人员','编制单位','编委','主编','参编','主要起草','主要审查',
            '设计单位','勘察单位','施工单位','监理单位','负责管理','归口','解释',
            'Standard for','Code for','Technical','General code',
        }
        def _has_page_number(h):
            """检测标题末尾是否有页码特征 (目次条目).
            正文标题无页码, 目次标题以"…… N"或"  N"结尾."""
            return bool(
                _re.search(r'……\s*\d{1,4}\s*$', h) or
                _re.search(r'\s{2,}\d{1,4}\s*$', h)
            )

        def _is_noise(h):
            h_s = h.replace(' ','').replace('\u3000','')
            for w in _FRONT_NOISE:
                if w in h_s: return True
            if _has_page_number(h):
                return True
            if len(h) > 60 and not _re.search(r'\d+\.\d+|[IVXLCDM\u2160-\u217B]+\s', h): return True
            return False

        # v6.18: 条文说明边界检测
        def _find_commentary_start(text, body_start=0):
            for m in _re.finditer(r'^#{1,3}\s+(.{0,80}?(?:条文说明|用词说明).*)$', text, _re.MULTILINE):
                if body_start > 0 and m.start() < body_start:
                    continue
                h = m.group(1).strip()
                if _is_noise(h):
                    continue
                return m.start()
            return None

        def _find_reference_start(text, body_start=0):
            for m in _re.finditer(r'^#{1,3}\s*引用标准名录', text, _re.MULTILINE):
                if body_start > 0 and m.start() < body_start:
                    continue
                return m.start()
            return None

        # v6.24: 正文起点检测 — 定位目次→跳过→找第一个正文章节
        def _find_body_start(text):
            """结构定位正文起点: 找到目次标记 → 跳过目次区域 → 第一个正文章节.

            目次中所有条目都含页码 (如 "8 注浆加固 75"), 正文标题不含页码.
            正文以 "1 总则" / "基本规定" / "1 一般规定" 等开头.
            """
            # Step 1: 找到目次/目录起点
            _toc_m = _re.search(
                r'^#{1,3}\s+(?:目\s*次|目\s*录|Contents)\s*$',
                text, _re.MULTILINE
            )
            _scan_start = _toc_m.end() if _toc_m else 0

            # Step 2: 在目次之后找正文起点标记 (不含页码)
            _BODY_PATTERNS = [
                r'^#{1,3}\s+\d+\s+总\s*则\s*$',
                r'^#{1,3}\s+总\s*则\s*$',
                r'^#{1,3}\s+基本规定\s*$',
                r'^#{1,3}\s+\d+\s+基本规定\s*$',
                r'^#{1,3}\s+\d+\s+一般规定\s*$',
                r'^#{1,3}\s+\d+\s+General\b',
            ]
            for pat in _BODY_PATTERNS:
                _m = _re.search(pat, text[_scan_start:], _re.MULTILINE)
                if _m:
                    return _scan_start + _m.start()

            # Step 3: 回退 — 目次后第一个无页码 + 长度>50 的标题
            for _m in _re.finditer(
                r'^(#{1,3})\s+(.+)$', text[_scan_start:], _re.MULTILINE
            ):
                h = _m.group(2).strip()
                if not _has_page_number(h) and len(h) > 3:
                    h_s = h.replace(' ', '').replace('\u3000', '')
                    if not any(w in h_s for w in _FRONT_NOISE):
                        return _scan_start + _m.start()
            return 0

        md_files = sorted([f for f in os.listdir(KB_MD_DIR) if f.endswith('.md')])
        idx = {}
        for fname in md_files:
            fpath = os.path.join(KB_MD_DIR, fname)
            try:
                text = open(fpath, 'r', encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            body_start = _find_body_start(text)
            com_start = _find_commentary_start(text, body_start)
            ref_start = _find_reference_start(text, body_start)
            sections = []
            for m in _re.finditer(r'^(#{1,3})\s+(.+)$', text, _re.MULTILINE):
                h = m.group(2).strip()
                pos = m.start()
                # 跳过正文起点之前的所有内容 (前言/目录/目次)
                if body_start > 0 and pos < body_start:
                    continue
                if _is_noise(h):
                    continue
                # v6.18: type 标注
                if com_start is not None and pos >= com_start:
                    stype = 'commentary'
                elif '附录' in h:
                    stype = 'appendix'
                elif ref_start is not None and pos >= ref_start:
                    stype = 'reference'
                else:
                    stype = 'normative'
                sections.append({'heading': h, 'pos': pos, 'type': stype})
            for i, s in enumerate(sections):
                s['length'] = (sections[i+1]['pos'] - s['pos']) if i+1 < len(sections) else (len(text) - s['pos'])
            if sections:
                idx[fname] = [{'heading': s['heading'], 'pos': s['pos'], 'length': s['length'], 'type': s['type']} for s in sections]
        self._search_cache = {
            '_meta': {'rebuilt': True, 'total_files': len(idx), 'total_sections': sum(len(v) for v in idx.values())},
            'index': idx
        }
        # 写回磁盘（下次启动无需重建）
        try:
            with open(SEARCH_INDEX, 'w', encoding='utf-8') as f:
                json.dump(self._search_cache, f, ensure_ascii=False)
        except OSError:
            pass  # 磁盘满/权限问题 → 仅内存缓存，不影响搜索
        import logging
        logging.warning(f'搜索索引已自动重建: {len(idx)}文件 '
                       f'{sum(len(v) for v in idx.values())}章节 → {SEARCH_INDEX}')

    def _legacy_keyword_search(self, keywords, max_results=10, project_standards=None,
                                vector_weight=0, must=None, must_not=None, prefer=None):
        """v6.24 遗留关键字搜索 — 保留用于编码查询 + Bool 过滤 (约5%流量)

        精确关键字匹配: 标题扫描 + BM25 正文 + 向量增强。
        """
        results = []
        prefer_tags = set(prefer) if prefer else set()
        must_terms = [t.lower() for t in (must or [])]
        not_terms = [t.lower() for t in (must_not or [])]
        pstandards = set(project_standards) if project_standards else set()

        vector_boosts = {}
        if vector_weight > 0:
            vector_boosts = self._get_vector_boosts(keywords)

        try:
            if self._search_cache is None:
                if not os.path.exists(SEARCH_INDEX):
                    self._rebuild_index_lite()
                else:
                    with open(SEARCH_INDEX, 'r', encoding='utf-8') as f:
                        self._search_cache = json.load(f)

            kw_list, _orig_kw_lower = self._prepare_legacy_keywords(keywords)

            index_data = self._search_cache.get('index', {})
            kw_lower_all = [kw.lower() for kw in kw_list]

            for fname, sections in index_data.items():
                text = self._load_legacy_file_text(fname)
                if text is None:
                    continue

                if not self._passes_legacy_bool_filters(text, must_terms, not_terms):
                    continue

                file_code = self._extract_code_from_filename(fname)
                in_project = (file_code in pstandards) if file_code and pstandards else False
                kw_rarity = self._idf_rarity_boost(kw_lower_all)
                kw_lower = kw_lower_all

                file_best_score = 0
                file_best_result = None
                file_kw_matched = set()
                file_total_hits = 0

                for sec_idx, sec in enumerate(sections[:200]):
                    # 跳过目录/目次条目 (含页码后缀: "…… 12" 或 "   12")
                    if re.search(r'(?:……\s*\d{1,4}|\s{2,}\d{1,4})\s*$',
                                 sec.get('heading', '')):
                        continue
                    segment = text[sec['pos']:sec['pos'] + sec['length']]
                    # 截断章节span中漏入的前言/引言/目次区域
                    _front_in_seg = re.search(r'(?:前\s*言|目\s*次|目\s*录|引\s*言)', segment)
                    if _front_in_seg:
                        segment = segment[:_front_in_seg.start()]
                    seg_lower = segment.lower()
                    matched_kw = [kw for kw in kw_lower if kw in seg_lower]
                    raw_hits = len(matched_kw)
                    if raw_hits == 0:
                        continue
                    weighted_hits = sum(kw_rarity.get(kw, 1.0) for kw in matched_kw)
                    for kw in matched_kw:
                        file_kw_matched.add(kw)
                    file_total_hits += raw_hits
                    heading = sec.get('heading', '')
                    hd_lower = heading.lower()
                    score = weighted_hits * 4.0
                    if raw_hits == len(kw_list):
                        score += 4.0
                    heading_hits = sum(1 for kw in kw_lower if kw in hd_lower)
                    score += heading_hits * 5.0
                    # 通用章节降权 + 技术章节加分
                    _hd_norm = re.sub(r'\s+', '', heading)
                    if re.match(r'^(?:[1-9]\d*\.?\s*)?(?:总\s*则|General|基本规定|一般要求|术语和符号|术语和定义|符号|范围|Scope|规范性引用文件|引用标准)$', _hd_norm):
                        score *= 0.01
                    elif re.match(r'^(?:[1-9]\d*\.)+[1-9]\d*\s*(?:一般规定|一般要求|General)$', _hd_norm):
                        score *= 0.3
                    elif re.search(r'\d+\.\d+\.\d+', heading):
                        score *= 1.3
                    if file_code:
                        code_hits = sum(1 for kw in kw_lower if kw in file_code.lower() or file_code.lower() in kw)
                        score += code_hits * 10.0
                    fname_lower = fname.lower()
                    fname_hits = sum(1 for kw in kw_lower if kw in fname_lower)
                    score += fname_hits * 8.0
                    # v8.0: 原始(未扩展)分词全命中文件名 → 绝对优势
                    fname_orig = sum(1 for kw in _orig_kw_lower if kw in fname_lower)
                    if fname_orig == len(_orig_kw_lower):
                        score += 100.0
                    if in_project:
                        score += 5.0
                    sl = sec['length']
                    if 300 < sl < 3000:
                        score += 1.0
                    elif sl > 5000:
                        score -= 1.0
                    if score > file_best_score:
                        file_best_score = score
                        file_best_result = {
                            'file': fname, 'heading': heading,
                            'hits': raw_hits, 'text': segment[:2000],
                        }

                if file_best_result:
                    coverage = len(file_kw_matched) / len(kw_list) if kw_list else 0
                    coverage_bonus = (coverage ** 3) * len(kw_list) * 3.0
                    file_best_score += coverage_bonus
                    if prefer_tags:
                        m = re.search(r'^categories:\s*\[(.*?)\]', text, re.MULTILINE)
                        if m:
                            file_tags = set(t.strip() for t in m.group(1).split(','))
                            if prefer_tags & file_tags:
                                file_best_score *= 1.5
                                file_best_result['tag_boost'] = True
                    file_best_result['score'] = round(file_best_score, 1)
                    file_best_result['hits'] = file_total_hits
                    results.append(file_best_result)

            if vector_boosts:
                for r in results:
                    file_code = self._extract_code_from_filename(r['file'])
                    if file_code and file_code in vector_boosts:
                        r['score'] = r['score'] + vector_boosts[file_code] * float(self._search_tuning.get('vector_boost_multiplier', 5.0)) * vector_weight
            results = self._merge_legacy_bm25_results(results, keywords)

            results = self._dedup_legacy_results(results)

        except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as e:
            import logging
            logging.warning(f'遗留搜索索引损坏({type(e).__name__}: {e})，重载中...')
            self._search_cache = None
            if os.path.exists(SEARCH_INDEX):
                try:
                    with open(SEARCH_INDEX, 'r', encoding='utf-8') as f:
                        self._search_cache = json.load(f)
                except Exception:
                    self._rebuild_index_lite()
            else:
                self._rebuild_index_lite()
            return self._legacy_keyword_search(keywords, max_results, project_standards,
                                               vector_weight, must, must_not, prefer)
        except Exception:
            import logging
            logging.warning('遗留搜索失败')

        results = self._trim_legacy_front_matter(results)

        return results[:max_results]

    def search(self, keywords, max_results=10, project_standards=None, vector_weight=0,
               must=None, must_not=None, prefer=None):
        """Search kb_search_index with heuristic ranking + optional vector boost + Bool filters
         + tag preference boost.

        Args:
            keywords: space-separated query terms (SHOULD semantics)
            must: list of terms — file is skipped if ANY term is missing
            must_not: list of terms — file is skipped if ANY term is present
            prefer: list of tags — matched files get score ×1.5 (no filtering, boost only)
        """
        cache_key = self._normalize_search_cache_key(
            keywords, max_results, project_standards, vector_weight, must, must_not, prefer
        )
        cached = self._get_cached_search_results(cache_key)
        if cached is not None:
            return cached[:max_results]

        # v6.23: 精确查询直通车 — 条款号/参数名直接定位, 绕过全文搜索
        # v8.0: 标准名查询先检测, 避免 param_index 子串误匹配
        _has_code, _is_std_name = self._classify_search_query(keywords)
        _title_direct = self._try_filename_title_lookup(keywords, max_results)
        if _title_direct:
            _title_direct = self._assign_confidence(_title_direct)
            _title_direct = self._set_trace(_title_direct, {'branch': 'filename_title'})
            self._cache_search_results(cache_key, _title_direct[:max_results])
            return _title_direct[:max_results]

        if not _is_std_name:
            _direct = self._try_direct_lookup(keywords)
            if _direct:
                _direct = self._apply_authority_boost(_direct)
                _direct.sort(key=lambda r: -(r.get('score', 0) if isinstance(r, dict) else 0))
                _direct = self._assign_confidence(_direct)
                for _r in _direct:
                    if isinstance(_r, dict):
                        _r['_trace'] = {'branch': 'direct', 'source': _r.get('_source', '?')}
                _direct = _direct[:max_results]
                self._cache_search_results(cache_key, _direct)
                return _direct

        # v7.0: PPR+LLM 双引擎路由
        # 编码查询 / Bool 过滤 / 标准全名 → 遗留精确关键字搜索
        if _has_code or _is_std_name or must or must_not:
            _results = self._legacy_keyword_search(keywords, max_results, project_standards,
                                                   vector_weight, must, must_not, prefer)
            # v8.0: 标准名查询 — 过滤文件名 token 匹配率 < 50% 的噪音结果
            # v8.1: 口语化疑问查询即使以"规范"结尾也不过滤
            if _is_std_name:
                _results = self._filter_standard_name_results(keywords, _results)
            # v8.0: 追踪路由原因
            _results = self._set_trace(_results, {
                'branch': 'legacy',
                'reason': self._legacy_search_reason(_has_code, _is_std_name, must, must_not),
            })
            # authority boost 改写 score, 必须在重排+赋档之前; 否则排名按 boost 前的旧分,
            # confidence 也按旧分赋档 → 与最终 score 错位 (编码查询尤甚)。
            _results = self._apply_authority_boost(_results, keywords)
            _results.sort(key=lambda r: -(r.get('score', 0) if isinstance(r, dict) else 0))
            _results = self._assign_confidence(_results)

            # v8.0: 最低分数阈值 — 过滤无意义查询的 BM25 噪音
            # BM25-only 结果通常 4-8 分, 合法结果 ≥20
            _results = [r for r in _results if r.get('score', 0) >= 10.0]
            _results = _results[:max_results]
            self._cache_search_results(cache_key, _results)
            return _results

        # NL 技术查询 → PPR 发现 + 遗留精确 + LLM 排序 三者融合
        kw_list = keywords.split()
        _extra_kws = []
        for kw in kw_list:
            _extra_kws.extend(normalize_code_token(kw))
        if _extra_kws:
            kw_list = kw_list + [k for k in _extra_kws if k.lower() not in
                                 set(x.lower() for x in kw_list)]
        _term_extras = _expand_term_map_v3(kw_list) or _expand_term_map(kw_list)

        import time as _t
        _t0 = _t.time()

        # Stage 1: PPR (宽召回) + 遗留 (精匹配) — 并行执行 (v8.0)
        # 短查询跳过 PPR (< 4 字, 格PPR 无意义; 也避免 scipy CSR 线程崩溃)
        _skip_vector = _has_code or vector_weight <= 0  # v8.2: vector_weight=0 时完全跳过
        _skip_ppr = len(keywords) < 4
        ppr_candidates = []
        legacy_results = []

        # 预加载共享资源, 避免并行竞态
        self._ensure_search_cache_loaded()

        def _run_legacy():
            try:
                return self._legacy_keyword_search(
                    keywords, max_results=min(max_results * 2, 20),
                    project_standards=project_standards, vector_weight=0 if _skip_vector else vector_weight)
            except Exception:
                return []

        def _run_ppr():
            _inner_boosts = {}
            if not _skip_vector:
                try:
                    _inner_boosts = self._get_vector_boosts(keywords, top_k=10)
                except (json.JSONDecodeError, IOError):
                    pass
            try:
                from kb_ppr_engine import discover as _ppr_discover
                return _ppr_discover(
                    query=keywords,
                    max_results=min(max_results * 3, 30),
                    term_extras=_term_extras,
                    vector_boosts=_inner_boosts,
                )
            except Exception:
                return []

        if _skip_ppr:
            legacy_results = _run_legacy()
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=2) as _exec:
                _futures = {
                    _exec.submit(_run_legacy): 'legacy',
                    _exec.submit(_run_ppr): 'ppr',
                }
                for _f in as_completed(_futures):
                    _key = _futures[_f]
                    try:
                        if _key == 'legacy':
                            legacy_results = _f.result()
                        elif _key == 'ppr':
                            ppr_candidates = _f.result()
                    except (KeyError, TypeError):
                        pass

        # 合并候选池: PPR(宽召回) + 遗留(精匹配)
        # PPR 原始 0-100000 → 除 40 对齐 Legacy 分数 (0-100), 关键词匹配优先于图传播
        candidates = self._merge_nl_candidates(ppr_candidates, legacy_results)
        if not candidates:
            return []

        # Stage 2 prep: 为 PPR 候选补充章节标题作为语义素材
        # (前500字是前言/目录, 章节标题才是核心技术词)
        candidates = self._hydrate_nl_candidates(candidates)

        # Stage 2: 融合分排序
        candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
        results = candidates[:max_results]

        # 通用章节降权 (在 heading 补全之后执行, 确保生效)
        results = self._adjust_nl_section_scores(results)

        # Post: Tag preference boost
        results = self._apply_prefer_tag_boost(results, prefer)

        # v8.2: 引用权威性加成 —— 被引用越多的标准优先展示
        results = self._apply_authority_boost(results, keywords)

        # Post: Dedup segmented files
        results = self._dedup_segmented_results(results)
        results.sort(key=lambda x: -x['score'])

        # T1: 条款级语义精定位 — 命中文件内用句向量找回答查询的具体条款 (正文优先)
        _qvec = self._get_query_vector(keywords)
        results = self._refine_clause_targets(results, keywords, qvec=_qvec)

        # T2: 本地 clause 重排 (确定性底座, 与下方 DeepSeek rerank 并存)
        # 窗口与精炼一致 (top-5): 让文件内真正回答查询的条款上浮
        results = self._clause_rerank(results, top_k=5)

        # v8.1: C 层 — DeepSeek listwise 重排。本地优先: 当 clause 信号已就位,
        # 本地重排为权威, 跳过较慢且不稳的网络 rerank; 仅在无 clause 信号时降级使用。
        _has_clause_signal = any('_clause_sim' in r for r in results[:3])
        if not _has_clause_signal:
            try:
                results = self._llm_rerank(keywords, results)
            except Exception:
                pass

        _elapsed = (_t.time() - _t0) * 1000
        if _elapsed > 2000:
            import logging as _log_t
            _log_t.info('search(NL): ppr=%d legacy=%d merged=%d ranked=%d %.0fms',
                       len(ppr_candidates), len(legacy_results),
                       len(candidates), len(results), _elapsed)

        # 最终兜底: 截断所有结果中漏入的前言/引言/目次
        results = self._trim_intro_text(results)

        # v8.0: confidence 分级 + 最低分数阈值
        score_threshold = float(self._search_tuning.get('score_threshold', 10.0))
        results = [r for r in results if r.get('score', 0) >= score_threshold]
        results = self._assign_confidence(results)

        # v8.0: _trace 诊断字段
        _trace = self._build_nl_trace(
            ppr_candidates, legacy_results, candidates, _skip_ppr, _elapsed, _extra_kws, _term_extras)
        results = self._set_trace(results, _trace)

        results = results[:max_results]
        self._cache_search_results(cache_key, results)
        return results

    def _llm_rerank(self, query, candidates):
        """C layer: DeepSeek listwise 重排 top-3。
        触发条件: ①分数差距 < 20% ②口语化疑问查询"""
        if len(candidates) < 3:
            return candidates
        scores = [c.get('score', 0) for c in candidates[:3]]
        _is_question = any(w in query for w in
            ['怎么','如何','什么','哪些','多少','怎样','为何','为什么','怎么办','什么时候'])
        if not _is_question:
            if scores[0] <= 0 or scores[0] / max(scores[2], 0.01) > 1.2:
                return candidates
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            return candidates
        lines = []
        for i, c in enumerate(candidates[:3]):
            h = c.get('heading', '')[:80]
            t = c.get('text', '')[:150]
            lines.append(f"[{chr(65+i)}] {h}\n   {t}")
        prompt = ('重排以下3条建筑规范搜索结果。只输出排序(如 B>A>C)，不要任何解释。\n'
                  f'查询: {query}\n' + '\n'.join(lines))
        try:
            import requests as _req
            resp = _req.post(
                'https://api.deepseek.com/anthropic/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': 'deepseek-v4-flash', 'max_tokens': 1024,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=(1.5, 3))
            if resp.status_code == 200:
                data = resp.json()
                # deepseek-v4-flash 是推理模型: content 含 thinking + text 两块。
                # 优先取 text 块; 若被 max_tokens 截断导致 text 为空, 从 thinking 块兜底。
                text = ''
                thinking = ''
                for block in data.get('content', []):
                    if block.get('type') == 'text' and not text:
                        text = (block.get('text') or '').strip()
                    elif block.get('type') == 'thinking':
                        thinking = (block.get('thinking') or '').strip()
                ranking = _parse_rerank_order(text) or _parse_rerank_order(thinking)
                if ranking:
                    reranked_head = self._rewrite_head_scores([candidates[i] for i in ranking])
                    reranked = reranked_head + candidates[3:]
                    for i, c in enumerate(reranked[:3]):
                        c['_llm_rank'] = i + 1
                    return reranked
                else:
                    import logging as _log3
                    _log3.warning(f'_llm_rerank: unparseable text={text!r} thinking_len={len(thinking)}')
        except Exception:
            pass
        return candidates

    def list_missing(self, cited_codes):
        """Given a set of cited standard codes, return those NOT in KB"""
        cited_set = {normalize_code(c) for c in cited_codes}
        return cited_set - set(self.code_map.keys())

    def list_unused(self, cited_codes, keyword_filter=None):
        """Given cited codes, return KB standards NOT cited"""
        cited_set = {normalize_code(c) for c in cited_codes}
        kb_set = set(self.code_map.keys())
        unused = kb_set - cited_set
        if keyword_filter:
            unused = {c for c in unused if any(kw in c.lower() for kw in keyword_filter)}
        return sorted(unused)

    def _load_image_index(self):
        """Lazy-load image metadata index (v6.18)"""
        if self._image_index is not None:
            return self._image_index
        if os.path.exists(IMAGE_INDEX_PATH):
            with open(IMAGE_INDEX_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._image_index = data.get('entries', [])
        else:
            self._image_index = []
        return self._image_index

    def record_feedback(self, entry):
        """Append feedback entry to kb_feedback.jsonl (v6.18).

        entry: dict with type, query, and optional result_used/clause_cited/terms
        """
        import datetime
        entry.setdefault('ts', datetime.datetime.now().isoformat())
        try:
            os.makedirs(os.path.dirname(FEEDBACK_LOG), exist_ok=True)
            with open(FEEDBACK_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except IOError:
            pass  # 反馈记录失败不应影响主流程

    def search_images(self, query, max_results=10):
        """Search image context for relevant images (v6.18).

        匹配: 查询词 vs 图片上下文 (章节标题 + 前后文段)
        返回: [{image, code, section, context, file, offset, score}]
        """
        entries = self._load_image_index()
        if not entries:
            return []

        import jieba
        q_terms = set(t.strip() for t in jieba.lcut(query.lower()) if len(t.strip()) >= 2)
        if not q_terms:
            q_terms = set(query.lower().split())
        scored = []
        for e in entries:
            ctx = ((e.get('section') or '') + ' ' +
                   (e.get('context_before') or '') + ' ' +
                   (e.get('context_after') or '')).lower()
            score = sum(1 for t in q_terms if t in ctx)
            if score > 0:
                scored.append({
                    'image': e['image'],
                    'image_name': e['image_name'],
                    'code': e['code'],
                    'section': e['section'],
                    'context': (e.get('context_before', '') + ' ' + e.get('context_after', ''))[:300],
                    'file': e['file'],
                    'offset': e['offset'],
                    'score': score,
                })
        scored.sort(key=lambda x: -x['score'])
        return scored[:max_results]

    def _load_bm25(self):
        """Lazy-load BM25 body index (v6.18)"""
        if self._bm25_index is not None:
            return self._bm25_index
        if os.path.exists(BM25_INDEX_PATH):
            with open(BM25_INDEX_PATH, 'r', encoding='utf-8') as f:
                self._bm25_index = json.load(f)
        else:
            self._bm25_index = {}
        return self._bm25_index


    def _bm25_search(self, query, max_results=30):
        """Search body text via BM25 and return (file, heading, score) candidates.

        BM25 formula: IDF * (tf*(k1+1)) / (tf + k1*(1-b + b*dl/avgdl))
        Runs as PARALLEL entry to L1 heading search — does NOT modify existing pipeline.
        """
        bm = self._load_bm25()
        if not bm or not bm.get('index'):
            return []

        files_list = bm.get('_files', [])
        sections = bm.get('_sections', {})
        doc_lengths = bm.get('_doc_lengths', {})
        N = bm.get('_doc_count', 1)
        avgdl = bm.get('_avg_len', 100)
        k1 = bm.get('_k1', 1.5)
        b = bm.get('_b', 0.75)
        idx = bm['index']

        import jieba
        q_tokens = list(set(jieba.lcut(query.lower())))
        q_tokens = [t.strip() for t in q_tokens if len(t.strip()) >= 2]

        doc_scores = {}
        for term in q_tokens:
            postings = idx.get(term, [])
            if not postings:
                continue
            df = len(postings)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)

            for fid, sid, tf in postings:
                doc_id = f'{fid}:{sid}'
                dl = doc_lengths.get(doc_id, avgdl)
                tf_score = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
                doc_scores[doc_id] = doc_scores.get(doc_id, 0) + idf * tf_score

        # Build results
        results = []
        for doc_id, score in sorted(doc_scores.items(), key=lambda x: -x[1]):
            parts = doc_id.split(':')
            fid = int(parts[0])
            sid = int(parts[1])
            fname = files_list[fid] if fid < len(files_list) else None
            heading = sections.get(doc_id, '')
            if fname:
                results.append({
                    'file': fname,
                    'heading': heading,
                    'bm25_score': round(score, 2),
                    '_source': 'bm25_body'
                })
            if len(results) >= max_results:
                break
        return results

    def stats(self):
        # Count all index keys (excluding _ prefixed meta keys)
        total_keys = sum(1 for k in self.index if not k.startswith('_'))
        total_clauses = sum(len(v) if isinstance(v, (list, dict)) else 0
                           for k, v in self.index.items() if not k.startswith('_'))
        # code_map only covers keys with extractable standard codes (~3-5),
        # but the index actually has 59 standards. Stats report the true count.
        return {
            'standards': total_keys,
            'clauses': total_clauses,
            'standards_in_index': total_keys,
            'indexed_clauses': total_clauses,
            'code_mapped': len(self.code_map),  # only entries with extractable codes
            'md_files': len(self.md_list),
            'md_with_codes': len(self.md_codes),
            'standard_status_coverage': _status_coverage(self._standard_status_data),
            'search_tuning': {
                'score_threshold': self._search_tuning.get('score_threshold'),
                'rerank_enabled': self._search_tuning.get('rerank_enabled'),
                'rerank_top_k': self._search_tuning.get('rerank_top_k'),
                'path': self._search_tuning.get('_path', ''),
            },
        }


# ---- CLI ----
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    kb = KBResolver()

    if len(sys.argv) < 2:
        s = kb.stats()
        print(f"Knowledge Base: {s['standards']} standards, {s['clauses']} clauses, {s['md_files']} MD files")
        print(f"Index: {INDEX_PATH}")
        print(f"MD dir: {KB_MD_DIR}")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == 'check':
        code = sys.argv[2]
        nc = normalize_code(code)
        exists = kb.exists(code)
        md = kb.find_md(code)
        print(f'{code}: {"IN KB" if exists else "NOT FOUND"}')
        if exists:
            print(f'  Clauses: {kb.get_clause_count(code)}')
        if md:
            print(f'  MD file: {md}')

    elif cmd == 'read':
        code = sys.argv[2]
        clause = sys.argv[3] if len(sys.argv) > 3 else ''
        text = kb.read_clause(code, clause) if clause else None
        if text:
            print(text)
        else:
            md = kb.find_md(code)
            if md:
                with open(md, 'r', encoding='utf-8', errors='replace') as f:
                    print(f.read()[:5000])
            else:
                print(f'{code}: not found')

    elif cmd == 'search':
        # --project alone = auto-load from content/project.json
        # --project=NAME  = load from projects/NAME/content/project.json
        proj_flag = None
        query_parts = []
        for a in sys.argv[2:]:
            if a == '--project':
                proj_flag = 'auto'
            elif a.startswith('--project='):
                proj_flag = a.split('=', 1)[1]
            else:
                query_parts.append(a)
        query = ' '.join(query_parts)

        # Load project standards if --project specified
        pstandards = None
        if proj_flag:
            # Try project.json first
            content_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'content')
            pj_path = os.path.join(content_dir, 'project.json')
            if os.path.exists(pj_path):
                try:
                    with open(pj_path, 'r', encoding='utf-8') as f:
                        pj = json.load(f)
                    pstandards = set()
                    for codes in pj.get('matched_standards', {}).values():
                        for c in codes:
                            pstandards.add(normalize_code(c))
                except (json.JSONDecodeError, IOError):
                    pass
            if pstandards:
                print(f'Context: {len(pstandards)} project standards loaded\n')

        results = kb.search(query, project_standards=pstandards)
        if not results:
            print(f'(no results for query: {query})')
        for i, r in enumerate(results):
            print(f'\n[{i+1}] {r["file"][:50]} | {r["heading"]}')
            print(f'  score={r.get("score", "?")} hits={r["hits"]}')
            print(r['text'][:400])

    elif cmd == 'missing':
        codes = sys.argv[2:]
        missing = kb.list_missing(codes)
        if missing:
            print('NOT in KB:')
            for c in sorted(missing):
                print(f'  {c}')
        else:
            print('All codes found in KB')

    elif cmd == 'stats':
        s = kb.stats()
        print(json.dumps(s, ensure_ascii=False, indent=2))
