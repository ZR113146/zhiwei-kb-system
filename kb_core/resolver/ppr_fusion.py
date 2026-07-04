# -*- coding: utf-8 -*-
"""resolver.ppr_fusion: KBResolver 的 PprFusionMixin 方法组 (Step 3 拆分)。

从 kb_resolver_core 拆出, 方法体逐字保留。作为 mixin 被 KBResolver 继承,
共享 self 状态与跨组 self.method() 调用经 MRO 解析, 行为不变。
"""

import os, re

from ._common import (
    KB_MD_DIR,
)


class PprFusionMixin:

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

    def _hydrate_nl_candidates(self, candidates, qvec=None):
        """为缺文本的候选补全 heading/text。PPR 候选 (heading=文件名) 走 fallback。

        v10.0: fallback 从"取第一个非 TOC 章节"改为语义精定位 ——
        用 qvec 在该文件的所有条款向量中找最匹配的条款, 确保 PPR 候选
        的 heading 是真实条款号而非粗略章节名。
        """
        self._ensure_search_cache_loaded()
        index = (self._search_cache or {}).get('index', {})
        for candidate in candidates:
            if len(candidate.get('text', '')) >= 50:
                continue
            fname = candidate.get('file', '')
            if fname not in index or not index[fname]:
                continue
            sections = index[fname]
            cand_heading = candidate.get('heading', '') or ''
            cand_pos = candidate.get('pos')
            section = None
            if cand_heading and not cand_heading.startswith('_seg') and len(cand_heading) <= 60:
                for s in sections:
                    if s.get('heading', '') == cand_heading:
                        section = s
                        break
            if section is None and cand_pos:
                for s in sections:
                    if s.get('pos') == cand_pos:
                        section = s
                        break
            if section is None:
                # v10.0: 语义精定位 fallback (替代原"取第一个非 TOC 章节")。
                if qvec is not None:
                    section = self._semantic_best_section(fname, sections, qvec)
                if section is None:
                    # 向量不可用 → 回退原 heuristic
                    section = sections[0]
                    for alt in sections[:10]:
                        heading = alt.get('heading', '')
                        if re.search(r'(?:……\s*\d{1,4}|\s{2,}\d{1,4})\s*$', heading):
                            continue
                        heading_norm = re.sub(r'\s+', '', heading)
                        if re.match(r'^(?:[1-9]\d*\.?\s*)?(?:总\s*则|General|基本规定|一般要求|术语和符号|术语和定义|符号|范围|Scope|规范性引用文件|引用标准)$', heading_norm):
                            continue
                        if alt.get('length', 0) >= 100:
                            section = alt
                            break
                candidate['heading'] = section.get('heading', '')[:80]
            fpath = os.path.join(KB_MD_DIR, fname)
            if os.path.exists(fpath):
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as file_obj:
                        body = file_obj.read()
                    pos, length = section.get('pos', 0), section.get('length', 2000)
                    candidate['text'] = body[pos:pos + min(length, 2000)]
                    candidate['pos'] = pos
                except (KeyError, TypeError):
                    pass
            # v10.0: 从 heading 提取结构化条款号
            if 'clause_number' not in candidate:
                m = re.match(r'^(\d+(?:\.\d+)*)\s', candidate.get('heading', ''))
                if m:
                    candidate['clause_number'] = m.group(1)
        return candidates

    def _semantic_best_section(self, fname, sections, qvec):
        """在文件的条款向量中找与 qvec 语义最相似的条款 section。返回 section dict 或 None。"""
        try:
            cs = self._ensure_clause_searcher()
            if cs is None:
                return None
            hits = cs.search_clauses(qvec, top_k=1, file_filter=fname, min_similarity=0.45)
            if not hits:
                return None
            best = hits[0]
            target_heading = best.get('heading', '')
            for s in sections:
                if s.get('heading', '') == target_heading:
                    return s
        except Exception:
            pass
        return None
