# -*- coding: utf-8 -*-
"""resolver.clause_refine: KBResolver 的 ClauseRefineMixin 方法组 (Step 3 拆分)。

从 kb_resolver_core 拆出, 方法体逐字保留。作为 mixin 被 KBResolver 继承,
共享 self 状态与跨组 self.method() 调用经 MRO 解析, 行为不变。
"""

import os

from ._common import (
    _ROOT_DIR, _parse_rerank_order, normalize_code,
)


class ClauseRefineMixin:

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

    def _rewrite_head_scores(self, reordered_head):
        """重排后保持 score 与新位置单调一致: 把窗口内原有 score 降序重新分配到新顺序。

        重排器 (clause / LLM) 按自己的维度决定顺序后, score 若不回写, 下游纯 score 排序
        与可信度 (依赖 score) 会与展示顺序矛盾。此处让排第一的拿窗口最高分, 依次递减,
        使 rank / score / confidence 三者同源。原始 score 存入 _pre_rerank_score 备查。

        v9.0 修 B2: 原缺 self 形参, 被 self._rewrite_head_scores([list]) 调用时
        list 错位传给 reordered_head 之外、self 占位 → TypeError, 致 _clause_rerank
        一旦触发重排就崩 (静默失效, 因 top-k 长期无 _clause_sim 而从未真正执行)。"""
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
