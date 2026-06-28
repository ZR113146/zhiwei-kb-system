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
from resolver._common import *
from resolver._common import (
    _status_coverage, load_standard_status, status_for_code, normalize_status_code,
)
from resolver.legacy_search import LegacySearchMixin
from resolver.naming import NamingMixin
from resolver.clause_read import ClauseReadMixin
from resolver.query_classifier import QueryClassifierMixin


class KBResolver(LegacySearchMixin, NamingMixin, ClauseReadMixin, QueryClassifierMixin):
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
                _scripts = _os.path.join(_ROOT_DIR, 'pipeline')
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
