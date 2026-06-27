"""本地向量语义搜索 — FAISS C++ 后端

FAISS IndexFlatIP: 19789 条 BGE-M3 向量, 1024 维, 内积搜索 (cosine)。
用法：  from pipeline.kb_vector_search_local import LocalSemanticSearch
  se = LocalSemanticSearch()
  results = se.search('基坑支护', top_k=10)
"""

import os, json, sys
import numpy as np
import faiss

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FAISS_PATH = os.path.join(_ROOT, 'data', 'vectordb', 'vectors.faiss')
_META_PATH = os.path.join(_ROOT, 'data', 'vectordb', 'metadata.json')
_VECTOR_MAP_PATH = os.path.join(_ROOT, 'pipeline', 'kb_vector_map.json')
_CONFIG_PATH = os.path.join(_ROOT, 'kb_core', 'kb.json')

with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
    _cfg = json.load(f)

API_KEY = os.environ.get(_cfg['api']['siliconflow_key_env'], '')
EMBED_URL = _cfg['api']['embed_url']
EMBED_MODEL = _cfg['api']['embed_model']


class LocalSemanticSearch:
    def __init__(self):
        self._index = None
        self._metadata = []
        self._uuid_to_code = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._index = faiss.read_index(_FAISS_PATH)

        if os.path.exists(_META_PATH):
            with open(_META_PATH, 'r', encoding='utf-8') as f:
                self._metadata = json.load(f)

        if os.path.exists(_VECTOR_MAP_PATH):
            with open(_VECTOR_MAP_PATH, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            self._uuid_to_code = raw.get('uuid_to_code', {})

        self._loaded = True

    def _embed(self, text: str) -> np.ndarray:
        """SiliconFlow BGE-M3 嵌入 → L2 归一化"""
        if not API_KEY:
            raise RuntimeError(f'环境变量 {_cfg["api"]["siliconflow_key_env"]} 未设置')
        import urllib.request as _ur, ssl as _sl, json as _jsn
        _ctx = _sl.create_default_context()
        _ctx.maximum_version = _sl.TLSVersion.TLSv1_2
        _req = _ur.Request(EMBED_URL, method='POST')
        _req.add_header('Content-Type', 'application/json')
        _req.add_header('Authorization', f'Bearer {API_KEY}')
        _body = _jsn.dumps({'model': EMBED_MODEL, 'input': text,
                            'encoding_format': 'float'}).encode()
        _resp = _ur.urlopen(_req, _body, timeout=30, context=_ctx)
        data = _jsn.loads(_resp.read())
        vec = np.array(data['data'][0]['embedding'], dtype=np.float32)
        return vec / (np.linalg.norm(vec) + 1e-12)

    def embed(self, text: str) -> np.ndarray:
        """公开的查询嵌入接口 (供上层共享同一 qvec, 避免重复嵌入)。"""
        return self._embed(text)

    def search(self, query: str, top_k: int = 10, min_similarity: float = 0.3,
               code_filter: str = None, max_results: int = None) -> list:
        if max_results is not None:
            top_k = max_results
        self._load()
        qvec = self._embed(query)
        return self.search_with_qvec(qvec, top_k=top_k, min_similarity=min_similarity)

    def search_with_qvec(self, qvec, top_k: int = 10, min_similarity: float = 0.3) -> list:
        """用已计算好的归一化查询向量检索 (复用上层 embed 结果)。"""
        self._load()
        qvec = np.asarray(qvec, dtype=np.float32).reshape(-1)
        k = min(top_k, self._index.ntotal)
        distances, indices = self._index.search(qvec.reshape(1, -1), k)

        results = []
        for i in range(k):
            sim = float(distances[0][i])
            if sim < min_similarity:
                continue
            idx = int(indices[0][i])
            meta = self._metadata[idx] if idx < len(self._metadata) else {}
            loader_id = meta.get('loader_id', '')
            code = self._uuid_to_code.get(loader_id, '')
            results.append({
                'text': meta.get('text', '')[:500],
                'score': round(sim, 4),
                'similarity': round(sim, 4),
                'loader_id': loader_id,
                'code': code,
                '_source': 'vector_local',
            })
        return results

    def stats(self) -> dict:
        self._load()
        return {
            'vectors': self._index.ntotal,
            'dim': self._index.d,
            'backend': 'faiss',
            'metadata_entries': len(self._metadata),
            'uuid_entries': len(self._uuid_to_code),
            'model': EMBED_MODEL,
        }


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    se = LocalSemanticSearch()
    if len(sys.argv) < 2:
        s = se.stats()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        q = ' '.join(sys.argv[1:])
        results = se.search(q, top_k=5)
        for i, r in enumerate(results):
            print(f"\n[{i+1}] score={r['score']:.4f} code={r['code']}")
            print(r['text'][:300])