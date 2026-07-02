# -*- coding: utf-8 -*-
"""resolver.clause_read: KBResolver 的条款读取与定位 mixin。

从 kb_resolver_core 拆出的"读条文"方法组 (条款索引定位、MD 正文条款抽取、
结构化条文对象、交叉引用解析、条款级语义检索器)。作为 mixin 被 KBResolver
继承, 方法体逐字保留; 跨组 self.method() 调用 (search/exists/find_md/
_build_citation_object 等) 经 MRO 解析, 行为不变。
"""

import os, re, json

from ._common import (
    KB_JSON_DIR, KB_MD_DIR, SEARCH_INDEX,
    _is_toc_entry, normalize_code, normalize_status_code,
)


class ClauseReadMixin:

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
        # Appendix identifier ('A' / '\u9644\u5F55A' / 'A.1'): must resolve to the appendix
        # header/subsection, NOT the first normative clause that merely references
        # '\u9644\u5F55 A'. Detected only when it is not already a numeric clause.
        _m_app = re.match(r'^(?:\u9644\u5F55\s*)?([A-Za-z](?:\.\d+)*)$', clause_pattern.strip())
        appendix_target = _m_app.group(1).upper() if (_m_app and not is_clause_number) else None

        def _appendix_heading_matches(value):
            if not appendix_target:
                return False
            head = re.sub(r'^#+\s*', '', str(value or '')).strip()
            if '.' in appendix_target:  # subsection like A.1 -> heading leads with it
                return bool(re.match(re.escape(appendix_target) + r'(?![\w.])', head))
            return bool(re.match(r'\u9644\u5F55\s*' + re.escape(appendix_target) + r'(?!\w)', head))

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
                        heading = sec.get('heading', '')
                        heading_match = _appendix_heading_matches(heading) if appendix_target else _has_clause_pattern(heading)
                        if heading_match:
                            candidate = text[sec['pos']:sec['pos']+sec['length']].strip()[:3000]
                            if appendix_target or _has_clause_pattern(candidate):
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
                    if appendix_target:
                        _apat = re.escape(appendix_target) if '.' in appendix_target else r'附录\s*' + re.escape(appendix_target) + r'(?!\w)'
                        _am = re.search(r'(?m)^#*\s*' + _apat, text)
                        idx = _am.start() if _am else -1
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

    def _ensure_clause_searcher(self):
        """Lazy-load the clause-level vector searcher. Returns it or None."""
        if not hasattr(self, '_clause_searcher'):
            self._clause_searcher = None
            try:
                from kb_core.clause_vector_search import get_clause_searcher
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
