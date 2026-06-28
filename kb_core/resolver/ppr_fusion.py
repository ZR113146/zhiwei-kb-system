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
