# -*- coding: utf-8 -*-
"""resolver.query_classifier: KBResolver 的 QueryClassifierMixin 方法组 (Step 3 拆分)。

从 kb_resolver_core 拆出, 方法体逐字保留。作为 mixin 被 KBResolver 继承,
共享 self 状态与跨组 self.method() 调用经 MRO 解析, 行为不变。
"""

import os, re

from ._common import (
    KB_MD_DIR, TITLE_ALIAS_MAP, _CODE_PREFIX_ALT, _ROOT_DIR, extract_code, normalize_code, normalize_status_code,
)


class QueryClassifierMixin:

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

    @staticmethod
    def _param_value_zero_magnitude(value):
        """True if an extracted param value is a physically-meaningless zero
        (e.g. '0mm', '0', '0.0mm') — a known false-extraction pattern that must
        never be surfaced as an authoritative answer."""
        num = re.search(r'-?\d+(?:\.\d+)?', str(value or ''))
        if not num:
            return False
        try:
            return float(num.group()) == 0.0
        except ValueError:
            return False

    def _param_index_result(self, param_name, entry):        return {
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
                _valid = [_e for _e in _entries if not self._param_value_zero_magnitude(_e.get('value'))]
                _results = []
                for _e in _valid[:5]:
                    _results.append(self._param_index_result(_pname, _e))
                if _results:
                    return _results
                break

        return None
