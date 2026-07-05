# -*- coding: utf-8 -*-
"""resolver.legacy_search: KBResolver 的遗留关键词检索 (BM25) mixin。

从 kb_resolver_core 拆出的 legacy/BM25 检索方法组。作为 mixin 被 KBResolver
继承, 方法体逐字保留, self 状态与跨组 self.method() 调用经 MRO 解析, 行为不变。
"""

import os, re, json, math

from ._common import (
    KB_MD_DIR, SEARCH_INDEX, BM25_INDEX_PATH,
    normalize_code_token, _expand_term_map, _expand_term_map_v3,
)


class LegacySearchMixin:

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
                            'pos': sec.get('pos', 0),
                            'type': sec.get('type', ''),
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
                    # v10.0: 从 heading 提取结构化条款号 (供下游候选精定位)
                    clause_match = re.match(r'^(\d+(?:\.\d+)*)\s', heading)
                    if clause_match:
                        file_best_result['clause_number'] = clause_match.group(1)
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
