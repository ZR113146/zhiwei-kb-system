#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kb_resolver: shared knowledge base access layer for construction-plan-writer tools.

Consumed by: scan.py, verify.py, diff_docx.py
Data sources: kb.json paths (data/index/*.md, data/kb_json/kb_search_index.json)

Key insight: normalize standard codes once, use everywhere.

结构 (Step 3 重构): 前导层 (路径/编码归一化/术语映射) 已迁至 resolver._common,
本文件作为门面: 组装 KBResolver 并 re-export 公开符号, 历史导入保持不变。
"""

import os, re, json, sys, math

# 前导层: 常量 + 无状态模块函数 (见 resolver/_common.py)。
# `import *` 借助 _common.__all__ 取到全部 preamble 名 (含下划线名), 使本模块
# 命名空间与重构前等价 —— 类方法引用的 normalize_code / _expand_term_map /
# KB_JSON_DIR 等, 以及 external importers 依赖的公开名, 全部可见。
from kb_core.resolver._common import *
from kb_core.resolver._common import (
    _status_coverage, load_standard_status, status_for_code, normalize_status_code,
)
from kb_core.resolver.legacy_search import LegacySearchMixin
from kb_core.resolver.naming import NamingMixin
from kb_core.resolver.clause_read import ClauseReadMixin
from kb_core.resolver.query_classifier import QueryClassifierMixin
from kb_core.resolver.ranking import RankingMixin
from kb_core.resolver.ppr_fusion import PprFusionMixin
from kb_core.resolver.clause_refine import ClauseRefineMixin
from kb_core.resolver.confidence import ConfidenceMixin


class KBResolver(LegacySearchMixin, NamingMixin, ClauseReadMixin, QueryClassifierMixin, RankingMixin, PprFusionMixin, ClauseRefineMixin, ConfidenceMixin):
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






    def _ensure_search_cache_loaded(self):
        if self._search_cache is None:
            try:
                if os.path.exists(SEARCH_INDEX):
                    with open(SEARCH_INDEX, 'r', encoding='utf-8') as cache_file:
                        self._search_cache = json.load(cache_file)
            except Exception:
                pass



    def _trim_intro_text(self, results):
        for result in results:
            result_text = result.get('text', '')
            if result_text and len(result_text) > 50:
                cut = re.search(r'(?:前\s*言|目\s*次|目\s*录|引\s*言)', result_text)
                if cut and cut.start() < 300:
                    result['text'] = result_text[:cut.start()]
        return results


    def _ensure_clause_index_loaded(self):
        if not hasattr(self, '_clause_index'):
            clause_index_path = os.path.join(KB_JSON_DIR, 'kb_clause_index.json')
            if os.path.exists(clause_index_path):
                with open(clause_index_path, 'r', encoding='utf-8') as file_obj:
                    self._clause_index = json.load(file_obj)
            else:
                self._clause_index = {'lookup': {}}
        return self._clause_index



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


    _GENERIC_TITLES = {
        '中国工程建设协会标准', '中国工程建设标准化协会标准',
        '中华人民共和国国家标准', '中华人民共和国行业标准',
        '中华人民共和国住房和城乡建设部', '中华人民共和国国家质量监督检验检疫总局',
        '前言', '目次', '目录', '总则', '术语', '基本规定',
    }

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


    def search(self, keywords, max_results=10, project_standards=None, vector_weight=0,
               must=None, must_not=None, prefer=None):
        """Search kb_search_index with heuristic ranking + optional vector boost + Bool filters
         + tag preference boost.

        路由器: 缓存检查 → 查询分类 → 选 branch (filename_title / direct / legacy / NL融合)。
        各 branch 的具体实现见对应 _*_branch 方法; branch 内部负责自己的缓存写入
        (NL branch 无候选时 `return []` 不写缓存, 此行为由 branch 方法保留)。

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

        # branch: 文件名/标题直接命中
        _title_direct = self._try_filename_title_lookup(keywords, max_results)
        if _title_direct:
            return self._finalize_title_branch(cache_key, _title_direct, max_results)

        # branch: 条款号/参数名精确直通 (标准名查询除外, 避免子串误匹配)
        if not _is_std_name:
            _direct = self._try_direct_lookup(keywords)
            if _direct:
                return self._finalize_direct_branch(cache_key, _direct, max_results)

        # v7.0: PPR+LLM 双引擎路由
        # branch: 编码查询 / Bool 过滤 / 标准全名 → 遗留精确关键字搜索
        if _has_code or _is_std_name or must or must_not:
            return self._run_legacy_branch(
                cache_key, keywords, max_results, project_standards, vector_weight,
                must, must_not, prefer, _has_code, _is_std_name)

        # branch: NL 技术查询 → PPR 发现 + 遗留精确 + LLM 排序 三者融合
        return self._run_nl_branch(
            cache_key, keywords, max_results, project_standards, vector_weight, prefer, _has_code)

    def _finalize_title_branch(self, cache_key, _title_direct, max_results):
        """branch: 文件名/标题命中的收尾 (赋档 + trace + 缓存)。"""
        _title_direct = self._assign_confidence(_title_direct)
        _title_direct = self._set_trace(_title_direct, {'branch': 'filename_title'})
        self._cache_search_results(cache_key, _title_direct[:max_results])
        return _title_direct[:max_results]

    def _finalize_direct_branch(self, cache_key, _direct, max_results):
        """branch: 条款号/参数名直通的收尾 (权威加成 + 重排 + 赋档 + trace + 缓存)。"""
        _direct = self._apply_authority_boost(_direct)
        _direct.sort(key=lambda r: -(r.get('score', 0) if isinstance(r, dict) else 0))
        _direct = self._assign_confidence(_direct)
        for _r in _direct:
            if isinstance(_r, dict):
                _r['_trace'] = {'branch': 'direct', 'source': _r.get('_source', '?')}
        _direct = _direct[:max_results]
        self._cache_search_results(cache_key, _direct)
        return _direct

    def _run_legacy_branch(self, cache_key, keywords, max_results, project_standards,
                           vector_weight, must, must_not, prefer, _has_code, _is_std_name):
        """branch: 编码/Bool/标准全名 → 遗留精确关键字搜索 (BM25)。"""
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

    def _run_nl_branch(self, cache_key, keywords, max_results, project_standards,
                       vector_weight, prefer, _has_code):
        """branch: NL 技术查询 → PPR 发现 + 遗留精确 + LLM 排序 三者融合。

        无候选时 `return []` 不写缓存 (保留原 search 行为)。
        """
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
                from kb_core.kb_ppr_engine import discover as _ppr_discover
                return _ppr_discover(
                    query=keywords,
                    max_results=min(max_results * 3, 30),
                    term_extras=_term_extras,
                    vector_boosts=_inner_boosts,
                )
            except Exception:
                return []

        # v9.0: 串行执行 (去 ThreadPool)。原并行靠 as_completed 完成顺序非定,
        # 致 ppr+legacy 分支 ~16% 跨进程漂移; PPR 仅 4% 边际收益, 不值背非确定性债。
        # 固定顺序 legacy → ppr, 结果可复现。
        legacy_results = _run_legacy()
        if not _skip_ppr:
            ppr_candidates = _run_ppr()

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
        results = self._refine_clause_targets(results, keywords, qvec=_qvec, top_n=15)

        # T2: 本地 clause 重排 (确定性底座, 与下方 DeepSeek rerank 并存)
        # 窗口与精炼一致: 让文件内真正回答查询的条款上浮
        results = self._clause_rerank(results, top_k=15)

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
