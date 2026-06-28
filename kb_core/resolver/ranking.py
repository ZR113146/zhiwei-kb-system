# -*- coding: utf-8 -*-
"""resolver.ranking: KBResolver 的 RankingMixin 方法组 (Step 3 拆分)。

从 kb_resolver_core 拆出, 方法体逐字保留。作为 mixin 被 KBResolver 继承,
共享 self 状态与跨组 self.method() 调用经 MRO 解析, 行为不变。
"""

import os, re

from ._common import (
    KB_MD_DIR, _CODE_PREFIX_ALT, normalize_code,
)


class RankingMixin:

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
