#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v6.19 PPR 统一图索引 — 语义边权重构

设计原则 (区别于 v6.18 统计边权):
  1. 标题→文件边: ×20 语义权重 (出现在标题中的词对该文件有定义力)
  2. Bigram边: 每词只保留 top-10 (减少 74%→ ~25% 噪音)
  3. T→F : T→T 目标比率 ≈ 1:1 (平衡随机游走吸收速度)
  4. 罕见词→文件边: IDF 增强 (区分度高)
  5. 通用词 bigram 边: 限制出度 ("混凝土"不再有 8364 条边)

用法: python kb_ppr_graph.py
输出: data/kb_json/kb_ppr_graph.json
"""
import json, os, re, math, time, sys
from collections import defaultdict, Counter

# ═══════════════════════════════ 配置 ═══════════════════════════════
KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json')
PHRASE_MODEL = os.path.join(KB_DIR, 'kb_phrase_model.json')
TERM_INDEX = os.path.join(KB_DIR, 'kb_term_index.json')
SEARCH_INDEX = os.path.join(KB_DIR, 'kb_search_index.json')
BM25_INDEX = os.path.join(KB_DIR, 'kb_body_bm25.json')
OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_ppr_graph.json')

# 边权配置
HEADING_BOOST = 50.0          # 标题→文件 语义乘数 (补偿归一化稀释)
BIGRAM_TOP_K = 10             # 每词仅保留最强 bigram 搭档
BIGRAM_WEIGHT_SCALE = 0.02    # bigram 边基础权重 (很低, 仅提供广度)
COOC_WEIGHT_SCALE = 1.0       # 共现边基础权重
TERM_WEIGHT_SCALE = 3.0       # 术语→文件相对权重
BM25_WEIGHT_SCALE = 1.0       # BM25→文件基础权重
TARGET_TF_RATIO = 2.0         # T→F : T→T 目标边权比 (有效比率，匹配运行时×2)

# NLP 填充词 (不参与建图)
FILLERS = {
    '的', '和', '及', '与', '或', '等', '其', '之', '在', '中',
    '为', '不', '应', '可', '宜', '按', '将', '对', '了', '是',
    '被', '把', '从', '到', '使', '以', '用', '由', '也', '都',
    '但', '而', '且', '所', '这', '那', '该', '每', '各', '能',
    '会', '要', '有', '无', '上', '下', '前', '后', '内', '外',
    '采用', '进行', '用于', '符合', '满足', '根据', '按照',
    '大于', '小于', '不得', '必须', '不宜', '不应',
    '一个', '一种', '部分', '部位', '构件', '结构',
    '只', '仅', '尚', '均', '较', '较之', '极其',
}
_has_filler = lambda w: len(w) < 2 or w in FILLERS

# ═══════════════════════════════ 加载数据 ═══════════════════════════════

def load_phrase_model():
    """返回 {words: [word_str], w2id: {word: idx}, bigrams: [{w1,w2,freq}]}"""
    print('[1/6] 加载短语模型...', end=' ', flush=True)
    t0 = time.time()
    with open(PHRASE_MODEL, 'r', encoding='utf-8') as f:
        pm = json.load(f)
    words = pm['words']
    w2id = {w: i for i, w in enumerate(words)}
    # bg 格式: [word_i, word_j, freq]
    bigrams = []
    for entry in pm['bg']:
        wi, wj, freq = entry
        if wi >= len(words) or wj >= len(words): continue
        w1 = words[wi]
        w2 = words[wj]
        if _has_filler(w1) or _has_filler(w2): continue
        bigrams.append((wi, wj, freq))
    print(f'{len(words)}词 {len(bigrams):,}对 ({time.time()-t0:.1f}s)')
    return {'words': words, 'w2id': w2id, 'bigrams': bigrams}

def load_term_index():
    """返回 {index: {term: [(file_idx, tfidf_score)]}, cooc: [(w1,w2,prob)], files: [fname]}"""
    print('[2/6] 加载术语索引...', end=' ', flush=True)
    t0 = time.time()
    with open(TERM_INDEX, 'r', encoding='utf-8') as f:
        ti = json.load(f)
    files = ti.get('_files', [])
    fname_to_idx = {f: i for i, f in enumerate(files)}

    # term → [(file_idx, section_idx, tfidf)]
    term_data = {}
    raw_index = ti.get('index', {})
    for term, entries in raw_index.items():
        if _has_filler(term): continue
        parsed = []
        for e in entries:
            if isinstance(e, list) and len(e) >= 3:
                fid = e[0] if isinstance(e[0], int) else int(e[0])
                tfidf = e[2] if isinstance(e[2], (int, float)) else float(e[2])
                if fid < len(files):
                    parsed.append((fid, tfidf))
        if parsed:
            term_data[term] = parsed

    # co-occurrence: {term: {partner: prob}}
    cooc = []
    raw_cooc = ti.get('_cooccur', {})
    if isinstance(raw_cooc, dict):
        for w1, partners in raw_cooc.items():
            if _has_filler(w1): continue
            for w2, prob in partners.items():
                if _has_filler(w2): continue
                cooc.append((w1, w2, float(prob)))
    elif isinstance(raw_cooc, list):
        for entry in raw_cooc:
            if len(entry) >= 3:
                cooc.append((entry[0], entry[1], float(entry[2])))

    print(f'{len(term_data)}术语 {len(cooc):,}共现对 ({time.time()-t0:.1f}s)')
    return {'index': term_data, 'cooc': cooc, 'files': files, 'f2i': fname_to_idx}

def load_search_index():
    """返回 {files: [fname], sections: {fname: [heading_tokens]}}"""
    print('[3/6] 加载搜索索引 (提取标题)...', end=' ', flush=True)
    t0 = time.time()
    with open(SEARCH_INDEX, 'r', encoding='utf-8') as f:
        si = json.load(f)
    idx = si.get('index', {})
    import jieba
    heading_tokens = defaultdict(list)  # fname → [(token, count)]
    total_headings = 0
    for fname, sections in idx.items():
        token_counts = Counter()
        for sec in sections:
            h = sec.get('heading', '')
            if not h: continue
            total_headings += 1
            # Tokenize heading
            for t in jieba.lcut(h):
                t = t.strip()
                if _has_filler(t): continue
                token_counts[t] += 1
        if token_counts:
            heading_tokens[fname] = list(token_counts.items())

    print(f'{len(idx)}文件 {total_headings}标题 ({time.time()-t0:.1f}s)')
    return {'files': list(idx.keys()), 'heading_tokens': heading_tokens}

def load_bm25_index():
    """返回 {files: [fname], term_docs: {term: [(file_idx, score)]}}"""
    print('[4/6] 加载 BM25 索引...', end=' ', flush=True)
    t0 = time.time()
    with open(BM25_INDEX, 'r', encoding='utf-8') as f:
        bi = json.load(f)
    files = bi.get('_files', [])
    raw_index = bi.get('index', {})

    # term → [(file_idx, avg_score)]
    term_docs = {}
    for term, entries in raw_index.items():
        if _has_filler(term): continue
        # entries: [[file_idx, section_idx, bm25_score], ...]
        file_scores = defaultdict(float)
        file_counts = defaultdict(int)
        for e in entries:
            fid, _, score = e[0], e[1] if len(e) > 1 else 0, e[2] if len(e) > 2 else 1
            file_scores[fid] += float(score)
            file_counts[fid] += 1
        # Average score per file
        idf = math.log(max(len(files), 1) / max(len(file_scores), 1))
        result = []
        for fid, total_score in file_scores.items():
            avg = total_score / max(file_counts[fid], 1)
            result.append((fid, avg * idf))
        if result:
            term_docs[term] = result

    print(f'{len(files)}文件 {len(term_docs):,}术语 ({time.time()-t0:.1f}s)')
    return {'files': files, 'term_docs': term_docs}

# ═══════════════════════════════ 构建图 ═══════════════════════════════

def _add_cooc_edges(raw, ti, w2id):
    """1a. T→T 共现边 (强信号)。就地写入 raw, 返回新增边数。"""
    t0 = time.time()
    cooc_added = 0
    for w1, w2, prob in ti['cooc']:
        i1 = w2id.get(w1, -1)
        i2 = w2id.get(w2, -1)
        if i1 < 0 or i2 < 0: continue
        if prob <= 0: continue
        raw[i1].append((i2, 'cooc', prob * COOC_WEIGHT_SCALE))
        raw[i2].append((i1, 'cooc', prob * COOC_WEIGHT_SCALE))
        cooc_added += 2
    print(f'  共现边: {cooc_added:,} ({time.time()-t0:.1f}s)')
    return cooc_added


def _add_bigram_edges(raw, pm):
    """1b. T→T Bigram边 (弱, top-K)。就地写入 raw, 返回新增边数。"""
    t0 = time.time()
    bigram_by_src = defaultdict(list)
    for wi, wj, freq in pm['bigrams']:
        bigram_by_src[wi].append((wj, freq))
    bigram_added = 0
    for src, partners in bigram_by_src.items():
        # 排序, 取 top-K
        partners.sort(key=lambda x: -x[1])
        total_freq = sum(f for _, f in partners[:BIGRAM_TOP_K])
        if total_freq <= 0: continue
        for tgt, freq in partners[:BIGRAM_TOP_K]:
            prob = freq / total_freq * BIGRAM_WEIGHT_SCALE
            raw[src].append((tgt, 'bigram', prob))
            bigram_added += 1
    print(f'  Bigram边 (top-{BIGRAM_TOP_K}): {bigram_added:,} ({time.time()-t0:.1f}s)')
    return bigram_added


def _add_v2_semantic_edges(raw, w2id):
    """1c_v2. T→T V2语义边 (上下文词向量余弦, 弱桥接边)。返回新增边数。"""
    t0 = time.time()
    v2_added = 0
    v2_sug_path = os.path.join(os.path.dirname(__file__), 'kb_term_bge_suggestions.json')
    if os.path.exists(v2_sug_path):
        with open(v2_sug_path, 'r', encoding='utf-8') as f:
            v2_sug = json.load(f)
        for s in v2_sug.get('suggestions', []):
            cos = s.get('cosine', 0)
            if cos < 0.70: continue
            src_term = s.get('source', '')
            tgt_term = s.get('candidate', '')
            i1 = w2id.get(src_term, -1); i2 = w2id.get(tgt_term, -1)
            if i1 < 0 or i2 < 0: continue
            # Bidirectional weak semantic bridge
            raw[i1].append((i2, 'v2_semantic', cos * 0.06))
            raw[i2].append((i1, 'v2_semantic', cos * 0.06))
            v2_added += 2
    print(f'  V2语义边 (cos>0.7): {v2_added:,} ({time.time()-t0:.1f}s)')
    return v2_added


def _add_heading_edges(raw, si, w2id, n_terms, fname_to_fid):
    """1c. T→F 标题边 (×HEADING_BOOST 语义权重, 最强信号)。返回新增边数。"""
    t0 = time.time()
    heading_added = 0
    heading_tokens = si['heading_tokens']
    for fname, token_list in heading_tokens.items():
        fid = fname_to_fid.get(fname, -1)
        if fid < 0: continue
        tgt_node = n_terms + fid
        for token, count in token_list:
            tid = w2id.get(token, -1)
            if tid < 0: continue
            # 每出现一次标题命中 → HEADING_BOOST 权重
            weight = min(count, 10) * HEADING_BOOST
            raw[tid].append((tgt_node, 'heading', weight))
            heading_added += 1
    print(f'  标题边 (×{HEADING_BOOST:.0f}): {heading_added:,} ({time.time()-t0:.1f}s)')
    return heading_added


def _add_term_edges(raw, ti, w2id, n_terms, n_files, fname_to_fid):
    """1d. T→F 术语索引边 (IDF加权)。返回新增边数。"""
    t0 = time.time()
    term_added = 0
    term_index = ti['index']
    tf_file_names = ti['files']  # file_idx → file_name
    for term, entries in term_index.items():
        tid = w2id.get(term, -1)
        if tid < 0: continue
        df = len(entries)
        idf = math.log(max(n_files, 1) / max(df, 1))
        for file_idx, tfidf_score in entries:
            if file_idx >= len(tf_file_names): continue
            file_name = tf_file_names[file_idx]
            fid = fname_to_fid.get(file_name, -1)
            if fid < 0: continue
            weight = (tfidf_score * idf * TERM_WEIGHT_SCALE) if tfidf_score > 0 else (idf * TERM_WEIGHT_SCALE * 0.1)
            raw[tid].append((n_terms + fid, 'term', weight))
            term_added += 1
    print(f'  术语边: {term_added:,} ({time.time()-t0:.1f}s)')
    return term_added


def _add_bm25_edges(raw, bi, w2id, n_terms, fname_to_fid):
    """1e. T→F BM25 边 (中等权重)。返回新增边数。"""
    t0 = time.time()
    bm25_added = 0
    bm25_skipped = 0
    term_docs = bi['term_docs']
    bm_files = bi['files']
    # Build robust mapping: BM25 filename → graph fid
    # Match by extracted standard code, fall back to exact name match
    def extract_code(fname):
        m = re.search(r'(GB|JGJ|CJJ|CECS|DB\d|JTG|TCECS)[\sT/\d\.\-]+', fname)
        return m.group(0).replace(' ', '') if m else fname[:30]
    bm_code_to_gfid = {}
    for fname, gfid in fname_to_fid.items():
        code = extract_code(fname)
        bm_code_to_gfid[code] = gfid
        bm_code_to_gfid[fname] = gfid  # also exact match
    for term, entries in term_docs.items():
        tid = w2id.get(term, -1)
        if tid < 0: continue
        has_heading = any(et == 'heading' for _, et, _ in raw.get(tid, []))
        has_term = any(et == 'term' for _, et, _ in raw.get(tid, []))
        for fid, score in entries:
            if fid >= len(bm_files):
                bm25_skipped += 1
                continue
            bm_fname = bm_files[fid]
            gfid = bm_code_to_gfid.get(bm_fname, -1)
            if gfid < 0:
                code = extract_code(bm_fname)
                gfid = bm_code_to_gfid.get(code, -1)
            if gfid < 0:
                bm25_skipped += 1
                continue
            weight = score * BM25_WEIGHT_SCALE
            if has_term: weight *= 0.3
            if has_heading: weight *= 0.5
            raw[tid].append((n_terms + gfid, 'bm25', max(weight, 0.001)))
            bm25_added += 1
    if bm25_skipped:
        print(f'  BM25 skipped: {bm25_skipped}')
    print(f'  BM25边: {bm25_added:,} ({time.time()-t0:.1f}s)')
    return bm25_added


def _normalize_edges(raw, n_terms):
    """阶段2: 归一化 + 压缩。返回 edges_out (list[list[(tgt, w_int)]])。"""
    print('  归一化边权...', end=' ', flush=True)
    t0 = time.time()
    edges_out = [[] for _ in range(n_terms)]  # 只有词节点有出边

    for src_id in range(n_terms):
        edge_list = raw.get(src_id, [])
        if not edge_list:
            continue

        # 分离 T→F 和 T→T 边, 分别归一化后按目标比例合并
        tf_raw = defaultdict(float)  # tgt → weight
        tt_raw = defaultdict(float)
        for tgt, etype, weight in edge_list:
            if tgt >= n_terms:
                tf_raw[tgt] += weight
            else:
                tt_raw[tgt] += weight

        tf_total = sum(tf_raw.values())
        tt_total = sum(tt_raw.values())

        total_ratio = TARGET_TF_RATIO + 1.0
        tf_share = TARGET_TF_RATIO / total_ratio
        tt_share = 1.0 / total_ratio
        combined = {}
        if tf_total > 0:
            for tgt, w in tf_raw.items():
                combined[tgt] = (w / tf_total) * tf_share
        if tt_total > 0:
            for tgt, w in tt_raw.items():
                combined[tgt] = combined.get(tgt, 0) + (w / tt_total) * tt_share

        # 转换为整数权重 (×10000)
        total_combined = sum(combined.values())
        if total_combined <= 0: continue
        for tgt, w in combined.items():
            w_int = max(1, int(w / total_combined * 10000))
            edges_out[src_id].append((tgt, w_int))

    # 统计
    total_edges = sum(len(row) for row in edges_out)
    tf_edges = sum(1 for row in edges_out for tgt, _ in row if tgt >= n_terms)
    tt_edges = total_edges - tf_edges
    print(f'{total_edges:,}边 T→F={tf_edges:,} T→T={tt_edges:,} ratio={tf_edges/max(tt_edges,1):.2f} ({time.time()-t0:.1f}s)')
    return edges_out


def build_graph(pm, ti, si, bi):
    """构建统一图: NODES + EDGES (编排各边收集与归一化步骤)"""
    print('[5/6] 构建图...')

    # ── 节点 ──
    words = pm['words']
    w2id = pm['w2id']
    n_terms = len(words)

    # 文件节点: 使用搜索索引的文件列表
    all_files = si['files']
    fname_to_fid = {f: i for i, f in enumerate(all_files)}
    n_files = len(all_files)
    total = n_terms + n_files
    print(f'  NODES: {n_terms}词 + {n_files}文件 = {total}')

    # ── 阶段1: 收集原始边 (term_src → target, weight) ──
    raw = defaultdict(list)  # src → [(tgt, weight_type, raw_weight)]
    cooc_added = _add_cooc_edges(raw, ti, w2id)
    bigram_added = _add_bigram_edges(raw, pm)
    _add_v2_semantic_edges(raw, w2id)
    heading_added = _add_heading_edges(raw, si, w2id, n_terms, fname_to_fid)
    term_added = _add_term_edges(raw, ti, w2id, n_terms, n_files, fname_to_fid)
    bm25_added = _add_bm25_edges(raw, bi, w2id, n_terms, fname_to_fid)

    # ── 阶段2: 归一化 + 压缩 ──
    edges_out = _normalize_edges(raw, n_terms)

    return {
        'words': words,
        'files': all_files,
        'edges': edges_out,
        'n_terms': n_terms,
        'n_files': n_files,
        'total': total,
        'edge_counts_by_type': {
            'cooc': cooc_added, 'bigram': bigram_added,
            'heading': heading_added, 'term': term_added, 'bm25': bm25_added,
        },
    }

# ═══════════════════════════════ 输出 ═══════════════════════════════

def save_graph(graph):
    """保存为紧凑 JSON (与旧格式兼容)"""
    print('[6/6] 保存图...', end=' ', flush=True)
    t0 = time.time()

    # 紧凑存储: edges[i] = [[tgt, w_int], ...]
    compact_edges = []
    for row in graph['edges']:
        if row:
            compact_edges.append([[t, w] for t, w in row])
        else:
            compact_edges.append([])

    output = {
        'words': graph['words'],
        'files': graph['files'],
        'edges': compact_edges,
        'n_terms': graph['n_terms'],
        'n_files': graph['n_files'],
        'total': graph['total'],
        '_meta': {
            'version': 'v6.19',
            'heading_boost': HEADING_BOOST,
            'bigram_top_k': BIGRAM_TOP_K,
            'target_tf_ratio': TARGET_TF_RATIO,
            'total_edges': sum(len(r) for r in compact_edges),
            'edge_counts_by_type': graph.get('edge_counts_by_type', {}),
        }
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    size_mb = os.path.getsize(OUTPUT) / (1024 * 1024)
    print(f'{size_mb:.1f}MB ({time.time()-t0:.1f}s)')

# ═══════════════════════════════ Main ═══════════════════════════════

def main():
    print('=' * 60)
    print('PPR 统一图构建器 v6.19 — 语义边权')
    print('=' * 60)

    t_total = time.time()

    pm = load_phrase_model()
    ti = load_term_index()
    si = load_search_index()
    bi = load_bm25_index()

    graph = build_graph(pm, ti, si, bi)
    save_graph(graph)

    # ── 验证 ──
    print()
    print('验证:')
    edges = graph['edges']
    total_e = sum(len(r) for r in edges)
    tf_e = sum(1 for r in edges for t, w in r if t >= graph['n_terms'])
    tt_e = total_e - tf_e
    print(f'  总边: {total_e:,}')
    print(f'  T→F: {tf_e:,} ({tf_e/max(total_e,1)*100:.1f}%)')
    print(f'  T→T: {tt_e:,} ({tt_e/max(total_e,1)*100:.1f}%)')
    print(f'  T→F/T→T: {tf_e/max(tt_e,1):.2f}')
    print(f'  文件数: {graph["n_files"]}')
    print(f'  词数: {graph["n_terms"]}')

    # 出度分布
    out_degrees = [len(r) for r in edges]
    import numpy as np
    print(f'  平均出度: {np.mean(out_degrees):.1f}')
    print(f'  中位出度: {np.median(out_degrees):.1f}')
    print(f'  最大出度: {np.max(out_degrees)}')
    print(f'  零出度节点: {sum(1 for d in out_degrees if d == 0)}')

    print(f'\n总耗时: {time.time()-t_total:.0f}s')
    print(f'输出: {OUTPUT}')

if __name__ == '__main__':
    main()
