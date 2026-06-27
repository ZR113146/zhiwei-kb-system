#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V2 上下文词向量 — 精确句子级上下文 + V1 回退

方法:
  1. 从 kb_sentence_text.json 加载 20,081 条句子文本
  2. jieba 分词 → 建 词→句子ID 倒排索引
  3. 词向量 = avg(该词所在句子的 FAISS 向量)
  4. 零向量词 (KB中不存在) → 回退到 V1 孤立 BGE 向量
"""
import json, os, sys, time, numpy as np
import jieba
from collections import defaultdict

KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
SENT_TEXT_PATH = os.path.join(KB_DIR, 'kb_sentence_text.json')
FAISS_PATH = os.path.join(KB_DIR, 'kb_sentence_vectors.faiss')
GRAPH_PATH = os.path.join(KB_DIR, 'kb_ppr_graph.json')
V1_PATH = os.path.join(KB_DIR, 'kb_word_vectors.npy')
V2_OUT = os.path.join(KB_DIR, 'kb_word_vectors_v2.npy')

def main():
    # 1. Load data
    print("Loading...")
    t0 = time.time()

    with open(GRAPH_PATH, 'r', encoding='utf-8') as f:
        graph = json.load(f)
    words = graph['words']; n_terms = graph['n_terms']
    w2id = {w: i for i, w in enumerate(words)}

    with open(SENT_TEXT_PATH, 'r', encoding='utf-8') as f:
        sent_texts = json.load(f)
    n_sent = len(sent_texts)

    # Load FAISS sentence vectors
    import faiss
    index = faiss.read_index(FAISS_PATH)
    dim = index.d
    sent_vecs = np.zeros((n_sent, dim), dtype=np.float32)
    index.reconstruct_n(0, n_sent, sent_vecs)
    print(f"  {len(words)} words, {n_sent} sentences, {dim}-dim vectors")

    # Load V1 for fallback (optional)
    if os.path.exists(V1_PATH):
        v1 = np.load(V1_PATH).astype(np.float32)
        print(f"  V1 loaded: {v1.shape}")
    else:
        v1 = None
        print("  V1 not found — zero-vector fallback")

    # 2. Pre-load PPR vocabulary into jieba
    print("Loading jieba vocabulary...")
    for w in words:
        if len(w) >= 2:
            jieba.add_word(w)
    print(f"  Done ({time.time()-t0:.0f}s)")

    # 3. Build word→sentence inverted index
    print("Building word→sentence index...")
    t1 = time.time()
    word_to_sids = defaultdict(list)

    for entry in sent_texts:
        sid = entry['sid']
        text = entry['text']
        tokens = [t.strip() for t in jieba.lcut(text) if len(t.strip()) >= 2]
        seen = set()
        for token in tokens:
            tid = w2id.get(token, -1)
            if tid >= 0 and tid not in seen:
                word_to_sids[tid].append(sid)
                seen.add(tid)

    n_mapped = len(word_to_sids)
    print(f"  {n_mapped}/{n_terms} words mapped ({time.time()-t1:.0f}s)")

    # 4. Compute V2: average of sentence vectors
    print("Computing V2 vectors...")
    t1 = time.time()
    v2 = np.zeros((len(words), dim), dtype=np.float32)
    count_zero = 0
    count_v1_fallback = 0

    for tid in range(n_terms):
        sids = word_to_sids.get(tid, [])
        if sids:
            # Cap at top 50 most frequent sentences to prevent oversmoothing
            if len(sids) > 50:
                sids = sids[:50]
            v2[tid] = sent_vecs[sids].mean(axis=0)
        else:
            count_zero += 1

    # Normalize V2
    norms = np.linalg.norm(v2, axis=1, keepdims=True) + 1e-10
    v2_norm = v2 / norms

    # 5. Fallback: zero vectors → V1 (if available)
    if v1 is not None:
        for tid in range(n_terms):
            if norms[tid] < 1e-9:
                v2_norm[tid] = v1[tid]
                count_v1_fallback += 1

    v2_out = v2_norm.astype(np.float16)
    print(f"  {count_zero} zero vectors → {count_v1_fallback} V1 fallbacks ({time.time()-t1:.0f}s)")

    # 6. Save
    np.save(V2_OUT, v2_out)
    size_mb = os.path.getsize(V2_OUT) / 1024 / 1024
    print(f"\nSaved: {V2_OUT} ({size_mb:.1f} MB, total {time.time()-t0:.0f}s)")

    # 7. Validate
    if v1 is not None:
        print("\nV2 validation (context + V1 fallback):")
        pairs = [("冷缝", "施工缝"), ("冷缝", "后浇带"), ("防水", "抗渗"),
                 ("桩基", "灌注桩"), ("保温", "隔热"), ("回填土", "压实填土"),
                 ("冷缝", "保温")]
        for a, b in pairs:
            ia, ib = w2id.get(a, -1), w2id.get(b, -1)
            if ia >= 0 and ib >= 0:
                v1c = float(np.dot(v1[ia], v1[ib]))
                v2c = float(np.dot(v2_out[ia].astype(np.float32), v2_out[ib].astype(np.float32)))
                d = v2c - v1c
                print(f"  {a:10s} <-> {b:10s}: V1={v1c:.4f} V2={v2c:.4f} ({d:+.4f})")

if __name__ == '__main__':
    main()
