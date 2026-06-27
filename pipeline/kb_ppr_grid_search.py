#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PPR 图参数网格搜索 — 找到规则能达到的 PPR 单独命中率上限

搜索三个正交参数:
  TARGET_TF_RATIO: T→F vs T→T 跨组分配 (1.0~8.0)
  HEADING_BOOST:   标题边在 T→F 组内权重 (20~200)
  BIGRAM_TOP_K:    Bigram 边数量/噪音控制 (3~20)

每个组合重建图, 测量 PPR 在多跳/罕见词/NL失败测试集上的命中率。

用法: python kb_ppr_grid_search.py
"""
import sys, os, json, time, re
from itertools import product

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KB_SKILL = os.path.join(SCRIPT_DIR, '..', 'kb_core')
if KB_SKILL not in sys.path:
    sys.path.insert(0, KB_SKILL)

import kb_ppr_graph as builder
from kb import KB, normalize_code, extract_code

sys.path.insert(0, SCRIPT_DIR)
from kb_ppr_quality import (
    MULTI_HOP_TESTS, RARE_TERM_TESTS,
    resolve_expected, extract_code_from_result,
)

# 12 条失败 NL 查询
FAILING_NL = [
    ('钢筋混凝土用钢 热轧带肋钢筋', ['GBT1499.2']),
    ('天然大理石建筑板材', ['GBT19766']),
    ('花岗岩铺装防碱背涂', ['GB50209', 'JGJ102']),
    ('外墙保温材料防火要求', ['GB50016', 'GBT10801.1']),
    ('施工现场扬尘控制', ['GB12523', 'GB16297']),
    ('外墙保温怎么防火', ['GB50016']),
    ('钢筋接头怎么错开位置', ['GB50010', 'GB50204']),
    ('大体积混凝土温控措施有哪些', ['GB50496', 'GB50204']),
    ('防火涂料厚度要求多少', ['GB50016', 'GB51249']),
    ('屋面女儿墙最小高度要求', ['GB50352']),
    ('冷缝处理措施有哪些', ['GB50204', 'GB50666']),
    ('回弹法检测混凝土强度怎么操作', ['JGJT23']),
]

REAL_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_ppr_graph.json')
BAK_PATH = REAL_PATH + '.grid_bak'

def measure(kb, test_cases):
    """PPR 单独搜索命中率 → (hits, total)"""
    r = kb._get_resolver()
    r._ppr_graph = None
    r._ppr_matrix = None
    if hasattr(r, '_ppr_code_to_fid'):
        r._ppr_code_to_fid = {}
    r._ppr_graph_search('混凝土', max_results=1)
    hits = 0
    for query, expected_codes in test_cases:
        expected = resolve_expected(expected_codes)
        results = r._ppr_graph_search(query, max_results=10)
        codes = [extract_code_from_result(res) for res in results]
        codes = [c for c in codes if c]
        if any(c in expected for c in codes):
            hits += 1
    return hits, len(test_cases)

def grid_search():
    tf_ratios = [1.0, 2.0, 3.0, 5.0, 8.0]
    heading_boosts = [20, 50, 100, 200]
    bigram_ks = [3, 5, 10, 20]
    total = len(tf_ratios) * len(heading_boosts) * len(bigram_ks)
    print(f"Grid: {len(tf_ratios)}x{len(heading_boosts)}x{len(bigram_ks)} = {total} combinations (~{total*9//60}min)\n")

    # 备份
    if os.path.exists(REAL_PATH) and not os.path.exists(BAK_PATH):
        import shutil
        shutil.copy2(REAL_PATH, BAK_PATH)
        print(f"Backed up: {BAK_PATH}\n")

    # 原始参数
    orig_tf, orig_hb, orig_bk = builder.TARGET_TF_RATIO, builder.HEADING_BOOST, builder.BIGRAM_TOP_K

    results = []; best_score = -1; best_params = None

    for idx, (tf, hb, bk) in enumerate(product(tf_ratios, heading_boosts, bigram_ks), 1):
        builder.TARGET_TF_RATIO = tf
        builder.HEADING_BOOST = hb
        builder.BIGRAM_TOP_K = bk

        t0 = time.time()
        try:
            pm = builder.load_phrase_model()
            ti = builder.load_term_index()
            si = builder.load_search_index()
            bi = builder.load_bm25_index()
            graph = builder.build_graph(pm, ti, si, bi)
            builder.save_graph(graph)  # writes to OUTPUT path

            kb2 = KB()
            mh_h, mh_t = measure(kb2, MULTI_HOP_TESTS)
            rt_h, rt_t = measure(kb2, RARE_TERM_TESTS)
            nl_h, nl_t = measure(kb2, FAILING_NL)
            all_h = mh_h + rt_h + nl_h
            all_t = mh_t + rt_t + nl_t

            elapsed = time.time() - t0
            tf_e = sum(1 for row in graph['edges'] for tgt, _ in row if tgt >= graph['n_terms'])
            tt_e = sum(len(row) for row in graph['edges']) - tf_e

            entry = {'tf': tf, 'hb': hb, 'bk': bk,
                     'mh': f"{mh_h}/{mh_t}", 'rt': f"{rt_h}/{rt_t}", 'nl': f"{nl_h}/{nl_t}",
                     'score': round(all_h/max(all_t,1), 3),
                     'edges': sum(len(r) for r in graph['edges']),
                     'tf_ratio': round(tf_e/max(tt_e,1), 2), 'time': round(elapsed,1)}
            results.append(entry)

            if entry['score'] > best_score:
                best_score = entry['score']; best_params = {'tf': tf, 'hb': hb, 'bk': bk}

            star = 'NEW BEST' if entry['score'] >= best_score else ''
            print(f"[{idx:3d}/{total}] TF={tf:.0f} HB={hb:3.0f} BK={bk:2d}  "
                  f"MH={mh_h}/{mh_t} RT={rt_h}/{rt_t} NL={nl_h}/{nl_t}  "
                  f"score={entry['score']:.3f}  {star}  ({elapsed:.0f}s)")
        except Exception as e:
            print(f"[{idx:3d}/{total}] TF={tf:.0f} HB={hb:3.0f} BK={bk:2d}  ERROR: {e}")
            results.append({'tf': tf, 'hb': hb, 'bk': bk, 'score': 0, 'error': str(e)})

    # 恢复
    builder.TARGET_TF_RATIO = orig_tf; builder.HEADING_BOOST = orig_hb; builder.BIGRAM_TOP_K = orig_bk
    return results, best_params, best_score

def print_report(results, best_params, best_score):
    print(f"\n{'='*70}")
    print(f"BEST: TF={best_params['tf']:.0f} HB={best_params['hb']:.0f} BK={best_params['bk']:.0f} score={best_score:.3f}")
    print(f"{'='*70}")
    print(f"{'TF':>4} {'HB':>4} {'BK':>3}  {'MH':>6} {'RT':>6} {'NL':>6}  {'Score':>6}  {'Edges':>8} {'TFr':>5} {'Time':>5}")
    for r in sorted(results, key=lambda x: -x['score'])[:25]:
        e = r.get('error','')
        if e:
            print(f"{r['tf']:4.0f} {r['hb']:4.0f} {r['bk']:3d}  {'ERR: '+e[:30]}")
        else:
            print(f"{r['tf']:4.0f} {r['hb']:4.0f} {r['bk']:3d}  {r['mh']:>6} {r['rt']:>6} {r['nl']:>6}  {r['score']:6.3f}  {r['edges']:>8,} {r['tf_ratio']:5.2f} {r['time']:4.0f}s")

    out = os.path.join(SCRIPT_DIR, 'kb_ppr_grid_results.json')
    json.dump({'best': best_params, 'best_score': best_score, 'results': results}, open(out,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"\nSaved: {out}")

if __name__ == '__main__':
    r, bp, bs = grid_search()
    print_report(r, bp, bs)
