"""BGE-M3 句子向量索引 — 34,132段正文 → FAISS 语义检索 (v6.18)

每段: 从BM25索引取章节正文 → BGE-M3 1024维嵌入 → FAISS IndexFlatIP
输出: data/kb_json/kb_sentence_vectors.faiss + data/kb_json/kb_sentence_meta.json
"""
import os, json, re, time, sys
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BM25_PATH = os.path.join(os.path.join(_ROOT, "data", "kb_json"), 'kb_body_bm25.json')
SEARCH_IDX_PATH = os.path.join(os.path.join(_ROOT, "data", "kb_json"), 'kb_search_index.json')
FAISS_OUT = os.path.join(os.path.join(_ROOT, "data", "kb_json"), 'kb_sentence_vectors.faiss')
META_OUT = os.path.join(os.path.join(_ROOT, "data", "kb_json"), 'kb_sentence_meta.json')

print("=" * 60)
print("BGE-M3 句子向量索引构建")
print("=" * 60)

# ---- 加载 BM25 索引, 取章节结构 ----
with open(BM25_PATH, 'r', encoding='utf-8') as f:
    bm = json.load(f)
files_list = bm.get('_files', [])
sections_dict = bm.get('_sections', {})
doc_count = bm.get('_doc_count', 0)
print(f"BM25: {len(files_list)} 文件 / {doc_count} 段")

# ---- 加载搜索索引, 取pos ----
with open(SEARCH_IDX_PATH, 'r', encoding='utf-8') as f:
    si = json.load(f)
si_idx = si.get('index', {})
print(f"搜索索引: {sum(len(v) for v in si_idx.values())} 章节")

# ---- 提取正文 ----
print("\n提取正文...")
texts = []      # 段文本
meta = []       # 元数据
skipped = 0

for fid, fname in enumerate(files_list):
    fpath = os.path.join(os.path.join(_ROOT, "data", "index"), fname)
    if not os.path.exists(fpath):
        skipped += doc_count // len(files_list) if files_list else 0
        continue
    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()

    sections = si_idx.get(fname, [])
    for sid, sec in enumerate(sections):
        doc_id = f'{fid}:{sid}'
        if doc_id not in sections_dict:
            continue  # 被BM25跳过的短段
        pos = sec.get('pos', 0)
        length = sec.get('length', 500)
        body = text[pos:pos+length][:2000]  # 最多2000字符

        if len(body) < 20:
            skipped += 1
            continue

        heading = sec.get('heading', '')
        texts.append(body)
        meta.append({
            'file': fname,
            'heading': heading,
            'fid': fid,
            'sid': sid,
            'type': sec.get('type', 'normative'),
        })

print(f"提取: {len(texts)} 段 ({skipped} 跳过)")

# ---- BGE-M3 嵌入 (SiliconFlow API) ----
import httpx, os as _os, time as _time
_API_KEY = _os.environ.get('SILICONFLOW_API_KEY', '')
_API_URL = 'https://api.siliconflow.cn/v1/embeddings'
_BATCH = 16  # Smaller batch to avoid rate limits
_total_batches = (len(texts) + _BATCH - 1) // _BATCH
print(f"\nBGE-M3 API 嵌入 ({len(texts)} 段, {_total_batches} 批, 约需{_total_batches*0.5:.0f}秒)...")

embeddings_list = []
_retry_count = 0
for _i in range(0, len(texts), _BATCH):
    _batch = texts[_i:_i+_BATCH]
    for _attempt in range(3):
        try:
            _resp = httpx.post(_API_URL, json={
                'model': 'BAAI/bge-m3',
                'input': _batch,
                'encoding_format': 'float'
            }, headers={'Authorization': f'Bearer {_API_KEY}'}, timeout=120)
            if _resp.status_code == 429:
                _retry_count += 1
                _time.sleep(2)  # Rate limit backoff
                continue
            _resp.raise_for_status()
            _data = _resp.json()
            for _item in _data['data']:
                embeddings_list.append(_item['embedding'])
            break
        except Exception as _e:
            if _attempt == 2:
                print(f"\n  FAIL at {_i}: {_e}")
                raise
            _time.sleep(1)
    _time.sleep(0.1)  # Short delay between requests
    if (_i // _BATCH) % 40 == 0:
        print(f"  {_i+len(_batch)}/{len(texts)} ({(_i+len(_batch))*100//len(texts)}%) retries={_retry_count}")

embeddings = np.array(embeddings_list, dtype=np.float32)
# Normalize for inner product
embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
print(f"嵌入完成: {embeddings.shape}")

# ---- FAISS 存储 ----
print("\nFAISS 索引构建...")
import faiss
dim = embeddings.shape[1]  # 1024
index = faiss.IndexFlatIP(dim)  # Inner Product (cosine for normalized vectors)
index.add(embeddings.astype('float32'))
print(f"FAISS 索引: {index.ntotal} 向量 / {dim} 维")

faiss.write_index(index, FAISS_OUT)

# ---- 元数据 ----
with open(META_OUT, 'w', encoding='utf-8') as f:
    json.dump(meta, f, ensure_ascii=False)

size_faiss = os.path.getsize(FAISS_OUT) / 1024 / 1024
size_meta = os.path.getsize(META_OUT) / 1024 / 1024
print(f"\n输出:")
print(f"  {FAISS_OUT} ({size_faiss:.0f}MB)")
print(f"  {META_OUT} ({size_meta:.0f}MB)")
print(f"  总计: {size_faiss+size_meta:.0f}MB")
