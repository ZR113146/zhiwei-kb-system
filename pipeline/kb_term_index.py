#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""术语索引构建器 (v6.17) — 三坐标倒排 + 术语共现矩阵

结构: term → [[file_id, section_id, offset], ...]
      _files: [filename, ...]
      _headings: {"fid:sid": heading}
      _cooccur: {term: {term: count}}  — 同章节共现统计

用法:
  python kb_term_index.py                    # 全量重建
  python kb_term_index.py --incremental       # Phase C2 增量

输出: data/kb_json/kb_term_index.json (~1.5MB)
"""

import os, sys, re, json, time, math
from collections import defaultdict, Counter

_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
if _KB_DIR not in sys.path:
    sys.path.insert(0, _KB_DIR)
from kb import load_config

_cfg = load_config()
KB_MD_DIR = os.path.expanduser(_cfg['paths']['kb_md'])
KB_JSON_DIR = os.path.expanduser(_cfg['paths'].get('kb_json', os.path.join(KB_MD_DIR, '..', 'kb_json')))
SEARCH_INDEX_PATH = os.path.join(KB_JSON_DIR, 'kb_search_index.json')
TERM_INDEX_PATH = os.path.join(KB_JSON_DIR, 'kb_term_index.json')
TERM_MAP_PATH = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'term_map.json')


def load_known_terms():
    """加载术语映射表 — 键和值都作为已知术语"""
    if not os.path.exists(TERM_MAP_PATH):
        return set()
    with open(TERM_MAP_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    terms = set()
    for k, vs in data.items():
        if len(k) >= 2:
            terms.add(k)
        for v in vs:
            if len(v) >= 2:
                terms.add(v)
    return terms


def _clean(text):
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\$[^$]+\$', ' ', text)
    text = re.sub(r'\$\$[^$]+\$\$', ' ', text)
    return text


def build_term_index(incremental=False):
    """构建三坐标倒排索引 + 术语共现矩阵"""
    if not os.path.exists(SEARCH_INDEX_PATH):
        print('[TermIndex] 搜索索引不存在, 跳过')
        return None

    with open(SEARCH_INDEX_PATH, 'r', encoding='utf-8') as f:
        search_idx = json.load(f)

    known_terms = load_known_terms()
    if not known_terms:
        print('[TermIndex] 术语映射表为空, 跳过')
        return None

    index_data = search_idx.get('index', {})

    # 已存在的索引 (增量模式)
    files = []
    file_id_map = {}
    heading_map = {}  # "fid:sid" → heading
    inverted = defaultdict(list)  # term → [[fid, sid, offset], ...]
    cooccur = defaultdict(Counter)  # term → {term: count}

    t0 = time.time()
    files_scanned = 0

    for fname, sections in index_data.items():
        fpath = os.path.join(KB_MD_DIR, fname)
        if not os.path.exists(fpath):
            continue

        fid = len(files)
        files.append(fname)
        file_id_map[fname] = fid
        files_scanned += 1

        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except Exception:
            continue

        for sec_idx, sec in enumerate(sections):
            start = sec['pos']
            end = min(len(text), start + sec['length'] + 500)
            body = _clean(text[start:end])

            heading_map[f'{fid}:{sec_idx}'] = sec['heading'][:60]

            # 该章节内出现的术语集合
            in_section = set()
            for term in known_terms:
                pos = body.find(term)
                if pos >= 0:
                    inverted[term].append([fid, sec_idx, pos])
                    in_section.add(term)

            # 共现统计: 同一章节内任意两个术语
            in_list = list(in_section)
            for i in range(len(in_list)):
                for j in range(i + 1, len(in_list)):
                    cooccur[in_list[i]][in_list[j]] += 1
                    cooccur[in_list[j]][in_list[i]] += 1

    # 共现转成概率表: 只保留 top-15 搭档
    cooccur_probs = {}
    for term, partners in cooccur.items():
        total = sum(partners.values())
        top = partners.most_common(15)
        cooccur_probs[term] = {p: round(c / total, 4) for p, c in top}

    # v6.17: 条目区分度过滤 — 泛化词(>5000条目)移除，保留区分性术语
    max_entries = max(len(v) for v in inverted.values()) if inverted else 1
    slim_index = {}
    removed_terms = []
    for term, entries in inverted.items():
        if len(entries) <= 5000:
            slim_index[term] = entries
        else:
            removed_terms.append(term)

    if removed_terms:
        print(f'  [瘦身] 移除{len(removed_terms)}个泛化词: {", ".join(removed_terms[:10])}')

    result = {
        '_meta': {
            'version': 2,
            'terms': len(slim_index),
            'total_entries': sum(len(v) for v in slim_index.values()),
            'files': files_scanned,
            'cooccur_pairs': sum(len(v) for v in cooccur_probs.values()),
            'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        },
        '_files': files,
        '_headings': heading_map,
        'index': slim_index,
        '_cooccur': cooccur_probs,
    }

    with open(TERM_INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)

    elapsed = time.time() - t0
    sz = os.path.getsize(TERM_INDEX_PATH)

    print(f'[TermIndex] {len(inverted)} 词 / {result["_meta"]["total_entries"]:,} 条目'
          f' / {result["_meta"]["cooccur_pairs"]:,} 共现对'
          f' / {sz/1024/1024:.1f}MB'
          f' / {elapsed:.1f}s → {TERM_INDEX_PATH}')
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--incremental', action='store_true')
    args = p.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    build_term_index(incremental=args.incremental)
