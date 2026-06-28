"""条款级语义检索 — 复用已建的句向量索引 (kb_sentence_vectors.faiss)。

与 kb_vector_search_local 的区别:
  - 后者是文档级 (返回 standard code, 用于排序加成)
  - 本模块是条款/章节级 (返回 file+heading+type, 用于把命中结果精定位到具体条款)

不自己 embed: 调用方传入已归一化的查询向量 (qvec), 一次嵌入多处复用。
索引粒度: 31670 条 BGE-M3 1024 维向量, 每条 = 一个章节正文; meta 带 file/heading/type。
"""

import json
import os

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_paths():
    # A1(消造轮子): 统一走 kb.load_config 唯一正主, 不再自解析 kb.json。
    # 局部 import 避免顶层导入环(本模块被 clause_read 函数内局部 import)。
    from kb import load_config
    paths = load_config().get('paths', {})

    def _resolve(key, default):
        val = paths.get(key, default)
        return val if os.path.isabs(val) else os.path.join(_ROOT, val)

    return (
        _resolve('kb_sentence_vectors', 'data/kb_json/kb_sentence_vectors.faiss'),
        _resolve('kb_sentence_meta', 'data/kb_json/kb_sentence_meta.json'),
    )


class ClauseVectorSearch:
    """惰性加载的条款级向量检索器 (模块级单例由 get_clause_searcher 提供)。"""

    def __init__(self):
        self._index = None
        self._meta = []
        self._file_to_rows = {}  # file -> [meta row indices]
        self._loaded = False
        self._available = None

    def available(self):
        """索引文件是否存在 (不触发加载)。"""
        if self._available is None:
            faiss_path, meta_path = _load_paths()
            self._available = os.path.exists(faiss_path) and os.path.exists(meta_path)
        return self._available

    def _load(self):
        if self._loaded:
            return
        import faiss
        faiss_path, meta_path = _load_paths()
        self._index = faiss.read_index(faiss_path)
        with open(meta_path, 'r', encoding='utf-8') as f:
            self._meta = json.load(f)
        for row, m in enumerate(self._meta):
            self._file_to_rows.setdefault(m.get('file', ''), []).append(row)
        self._loaded = True

    def _row_payload(self, row, sim):
        m = self._meta[row]
        return {
            'file': m.get('file', ''),
            'heading': m.get('heading', ''),
            'type': m.get('type', 'normative'),
            'similarity': round(float(sim), 4),
            'row': row,
        }

    def search_clauses(self, qvec, top_k=10, file_filter=None, min_similarity=0.3):
        """返回最匹配的条款/章节 [{file, heading, type, similarity, row}]。

        qvec: 已归一化的 1024 维查询向量 (np.ndarray 或 list)。
        file_filter: 限定在某个 md 文件内检索 (用于把命中结果精定位到文件内最佳条款)。
        """
        if not self.available():
            return []
        self._load()
        q = np.asarray(qvec, dtype=np.float32).reshape(-1)
        if q.shape[0] != self._index.d:
            return []

        if file_filter is not None:
            rows = self._file_to_rows.get(file_filter, [])
            if not rows:
                return []
            # 精确点积 (文件内条款数有限, reconstruct 后内积)
            vecs = np.vstack([self._index.reconstruct(r) for r in rows])
            sims = vecs @ q
            order = np.argsort(-sims)[:top_k]
            out = [self._row_payload(rows[i], sims[i]) for i in order if sims[i] >= min_similarity]
            return out

        k = min(top_k, self._index.ntotal)
        sims, idx = self._index.search(q.reshape(1, -1), k)
        out = []
        for j in range(k):
            s = float(sims[0][j])
            if s < min_similarity:
                continue
            out.append(self._row_payload(int(idx[0][j]), s))
        return out


_SINGLETON = None


def get_clause_searcher():
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = ClauseVectorSearch()
    return _SINGLETON
