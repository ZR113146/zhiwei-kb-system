#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BGE 词向量辅助术语映射扩展

对已有术语映射的每个词, 找 BGE top-10 邻居,
过滤已在映射中的, 取 high-confidence (>0.6) 建议供人工审核。
"""
import json, os, sys, time, numpy as np
from collections import defaultdict

KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
TM_PATH = os.path.join(os.path.dirname(__file__), 'kb_term_map.json')
VEC_PATH = os.path.join(KB_DIR, 'kb_word_vectors_v2.npy')
GRAPH_PATH = os.path.join(KB_DIR, 'kb_ppr_graph.json')

def main():
    # 1. Load data
    with open(TM_PATH, 'r', encoding='utf-8') as f:
        term_map = json.load(f)
    with open(GRAPH_PATH, 'r', encoding='utf-8') as f:
        graph = json.load(f)
    words = graph['words']
    w2id = {w: i for i, w in enumerate(words)}
    bge = np.load(VEC_PATH).astype(np.float32)
    bge_norm = bge / (np.linalg.norm(bge, axis=1, keepdims=True) + 1e-10)

    # Build set of ALL terms in existing term_map (keys + values)
    existing_terms = set()
    for k, vals in term_map.items():
        existing_terms.add(k)
        existing_terms.update(vals)

    # Build set of KB-validated terms (in graph AND appear in KB)
    # Filter: must be in term index OR heading tokens
    si_path = os.path.join(KB_DIR, 'kb_search_index.json')
    with open(si_path, 'r', encoding='utf-8') as f:
        si = json.load(f)
    ti_path = os.path.join(KB_DIR, 'kb_term_index.json')
    with open(ti_path, 'r', encoding='utf-8') as f:
        ti = json.load(f)
    term_idx_terms = set(ti.get('index', {}).keys())

    heading_terms = set()
    import jieba
    for fname, sections in si.get('index', {}).items():
        for sec in sections:
            h = sec.get('heading', '')
            if h:
                for t in jieba.lcut(h):
                    t = t.strip()
                    if len(t) >= 2: heading_terms.add(t)

    kb_valid_terms = term_idx_terms | heading_terms
    print(f"Term map: {len(term_map)} groups, {len(existing_terms)} unique terms")
    print(f"KB validated terms: {len(kb_valid_terms)}")

    # 2. For each term map KEY, find BGE neighbors
    suggestions = []
    processed = set()

    for key_term in list(term_map.keys()):
        tid = w2id.get(key_term, -1)
        if tid < 0: continue
        if key_term in processed: continue
        processed.add(key_term)

        # Find BGE neighbors
        sims = bge_norm @ bge_norm[tid]
        top = np.argsort(-sims)

        for idx in top[:20]:
            neighbor = words[idx]
            sim = float(sims[idx])
            if neighbor == key_term: continue
            if sim < 0.60: break  # Confidence threshold
            if neighbor in existing_terms: continue
            if neighbor not in kb_valid_terms: continue
            if neighbor in processed: continue

            suggestions.append({
                'source': key_term,
                'candidate': neighbor,
                'cosine': round(sim, 3),
                'group': term_map[key_term][:5]  # Show existing group context
            })
            processed.add(neighbor)

    suggestions.sort(key=lambda x: -x['cosine'])

    # Also: for terms in the existing map VALUES, find reciprocal suggestions
    all_expanded = set()
    for vals in term_map.values():
        all_expanded.update(vals)

    for exp_term in all_expanded:
        tid = w2id.get(exp_term, -1)
        if tid < 0 or exp_term in processed: continue
        processed.add(exp_term)

        sims = bge_norm @ bge_norm[tid]
        top = np.argsort(-sims)
        for idx in top[:20]:
            neighbor = words[idx]
            sim = float(sims[idx])
            if neighbor == exp_term: continue
            if sim < 0.60: break
            if neighbor in existing_terms: continue
            if neighbor not in kb_valid_terms: continue
            if neighbor in processed: continue

            # Find which group(s) this expanded term belongs to
            parent_groups = [k for k, vals in term_map.items() if exp_term in vals]
            suggestions.append({
                'source': exp_term,
                'candidate': neighbor,
                'cosine': round(sim, 3),
                'parent_groups': parent_groups[:3]
            })
            processed.add(neighbor)

    suggestions.sort(key=lambda x: -x['cosine'])

    # 3. Output
    print(f"\nHigh-confidence suggestions (cos > 0.60, KB-validated): {len(suggestions)}")
    print(f"{'='*70}")

    # Group by cosine bands
    bands = {'>0.85': [], '0.75-0.85': [], '0.60-0.75': []}
    for s in suggestions:
        c = s['cosine']
        if c > 0.85: bands['>0.85'].append(s)
        elif c > 0.75: bands['0.75-0.85'].append(s)
        else: bands['0.60-0.75'].append(s)

    for band, items in bands.items():
        if not items: continue
        print(f"\n--- {band} ({len(items)} suggestions) ---")
        for s in items[:15]:
            source = s['source']
            cand = s['candidate']
            cos = s['cosine']
            ctx = s.get('group', s.get('parent_groups', ['?']))[:3]
            print(f"  {source:15s} +[{cand:15s}] cos={cos:.3f}  context={ctx}")

    # 4. Save for review
    out_path = os.path.join(os.path.dirname(__file__), 'kb_term_bge_suggestions.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'count': len(suggestions), 'suggestions': suggestions}, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(suggestions)} suggestions to: {out_path}")

    # 5. Auto-accept disabled for V2 (oversmoothing produces false positives at cos~1.0)
    # Suggestions saved for manual review only
    auto_count = 0
    # for s in suggestions:
    #     if s['cosine'] >= 0.98 and 'group' in s:  # V2 needs higher threshold
    for s in []:  # Disabled
            source = s['source']
            cand = s['candidate']
            if source in term_map and cand not in term_map[source]:
                term_map[source].append(cand)
                auto_count += 1
                print(f"  AUTO: {source} +[{cand}] (cos={s['cosine']:.3f})")

    if auto_count > 0:
        with open(TM_PATH, 'w', encoding='utf-8') as f:
            json.dump(term_map, f, ensure_ascii=False, indent=2)
        print(f"\nAuto-added {auto_count} high-confidence terms to term_map")
        print(f"Term map now: {len(term_map)} groups, {sum(len(v)+1 for v in term_map.values())} terms")

if __name__ == '__main__':
    main()
