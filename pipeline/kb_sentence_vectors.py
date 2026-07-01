# -*- coding: utf-8 -*-
"""BGE-M3 句子向量索引 — 章节/叶子条款级正文 → FAISS 语义检索。

现役 pipeline 成员(2026 从 archive 复归 + 现代化):路径统一走 kb.json/load_config,
API key/url/model 走 cfg['api'](对齐 kb_vector_search_local),不再裸 _ROOT/硬编码。

每段: 从 kb_search_index 的 section(pos/length/heading, 已含叶子条款分段)取正文
       → BGE-M3 1024维嵌入(SiliconFlow API)→ FAISS IndexFlatIP(内积=cosine)。
输出: paths['kb_sentence_vectors'] (.faiss) + paths['kb_sentence_meta'] (.json)
消费: kb_core/clause_vector_search.py(条款级语义检索)。

用法:
  python kb_sentence_vectors.py            # 全量重嵌(需 SILICONFLOW_API_KEY, 付费)
  python kb_sentence_vectors.py --dry-run  # 只统计待嵌段数, 不调 API(免费)

注意: .faiss/meta 被 gitignore, 非版本控制; 重嵌覆盖旧文件且 API 嵌入不可字节复现,
      重嵌前应手动备份。切块单位 = kb_search_index 的 section, 与 bm25/clause_index 同源同粒度。
"""
import os, json, sys, time
import numpy as np

from kb_core.kb import load_config
import kb_core.changelog as changelog; changelog.record(__file__, sys.argv)

_cfg = load_config()
_P = _cfg['paths']
KB_MD_DIR = _P['kb_md']
KB_JSON_DIR = _P['kb_json']
# bm25/search_index 无独立 kb.json 键, 统一从 kb_json 目录派生(全代码库约定)
BM25_PATH = os.path.join(KB_JSON_DIR, 'kb_body_bm25.json')
SEARCH_IDX_PATH = os.path.join(KB_JSON_DIR, 'kb_search_index.json')
FAISS_OUT = _P['kb_sentence_vectors']
META_OUT = _P['kb_sentence_meta']

_API = _cfg.get('api', {})
API_KEY_ENV = _API.get('siliconflow_key_env', 'SILICONFLOW_API_KEY')
API_URL = _API.get('embed_url', 'https://api.siliconflow.cn/v1/embeddings')
API_MODEL = _API.get('embed_model', 'BAAI/bge-m3')

_BATCH = 16
_MIN_BODY = 20   # 过短段跳过(与归档版一致)
_MAX_BODY = 2000


def collect_texts():
    """按 search_index section(与 bm25 交集)提取正文, 返回 (texts, meta)。"""
    with open(BM25_PATH, 'r', encoding='utf-8') as f:
        bm = json.load(f)
    files_list = bm.get('_files', [])
    sections_dict = bm.get('_sections', {})
    with open(SEARCH_IDX_PATH, 'r', encoding='utf-8') as f:
        si_idx = json.load(f).get('index', {})

    texts, meta, skipped = [], [], 0
    for fid, fname in enumerate(files_list):
        fpath = os.path.join(KB_MD_DIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
        for sid, sec in enumerate(si_idx.get(fname, [])):
            if f'{fid}:{sid}' not in sections_dict:
                continue  # 被 BM25 跳过的短段
            body = text[sec.get('pos', 0):sec.get('pos', 0) + sec.get('length', 500)][:_MAX_BODY]
            if len(body) < _MIN_BODY:
                skipped += 1
                continue
            texts.append(body)
            meta.append({
                'file': fname,
                'heading': sec.get('heading', ''),  # 逐字取 section heading, 保下游精确匹配
                'fid': fid,
                'sid': sid,
                'type': sec.get('type', 'normative'),
            })
    return texts, meta, skipped


def embed_texts(texts):
    """BGE-M3 批量嵌入 + L2 归一化, 返回 (n, dim) float32。"""
    import httpx
    api_key = os.environ.get(API_KEY_ENV, '')
    if not api_key:
        raise RuntimeError(f'环境变量 {API_KEY_ENV} 未设置')
    out, retries = [], 0
    n_batches = (len(texts) + _BATCH - 1) // _BATCH
    print(f'BGE-M3 嵌入 {len(texts)} 段 / {n_batches} 批...')
    for i in range(0, len(texts), _BATCH):
        batch = texts[i:i + _BATCH]
        for attempt in range(3):
            try:
                resp = httpx.post(API_URL, json={
                    'model': API_MODEL, 'input': batch, 'encoding_format': 'float'
                }, headers={'Authorization': f'Bearer {api_key}'}, timeout=120)
                if resp.status_code == 429:
                    retries += 1; time.sleep(2); continue
                resp.raise_for_status()
                for item in resp.json()['data']:
                    out.append(item['embedding'])
                break
            except Exception as e:
                if attempt == 2:
                    print(f'  FAIL at {i}: {e}'); raise
                time.sleep(1)
        time.sleep(0.1)
        if (i // _BATCH) % 40 == 0:
            print(f'  {i + len(batch)}/{len(texts)} ({(i + len(batch)) * 100 // len(texts)}%) retries={retries}')
    emb = np.array(out, dtype=np.float32)
    emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    return emb


def build(dry_run=False):
    texts, meta, skipped = collect_texts()
    print(f'提取: {len(texts)} 段待嵌 ({skipped} 跳过短段)')
    if dry_run:
        print('[dry-run] 不调 API, 不写文件。')
        return
    emb = embed_texts(texts)
    print(f'嵌入完成: {emb.shape}')
    import faiss
    index = faiss.IndexFlatIP(emb.shape[1])
    index.add(emb.astype('float32'))
    faiss.write_index(index, FAISS_OUT)
    with open(META_OUT, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f'FAISS: {index.ntotal} 向量 / {emb.shape[1]} 维')
    print(f'输出: {FAISS_OUT} ({os.path.getsize(FAISS_OUT)/1024/1024:.0f}MB)')
    print(f'      {META_OUT} ({os.path.getsize(META_OUT)/1024/1024:.0f}MB)')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='BGE-M3 句子向量索引构建')
    ap.add_argument('--dry-run', action='store_true', help='只统计段数, 不调 API')
    build(dry_run=ap.parse_args().dry_run)
