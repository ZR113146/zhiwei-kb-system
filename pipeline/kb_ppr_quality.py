#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PPR 图传播质量门 — 测量 OLD 搜索测不到的能力

四类测试:
  消歧: 同一词不同语境 → PPR 结果应可分离
  多跳: 查询词不在目标文件中 → PPR 通过图中继到达
  罕见词桥接: 低频术语 → PPR 通过共现路径找到相关标准
  图结构健康: 孤立节点/连通分量/边权分布

用法:
  python kb_ppr_quality.py               # 评估并打印报告
  python kb_ppr_quality.py --baseline     # 保存基线
  python kb_ppr_quality.py --check        # 对比基线, 退化则 exit 1
"""
import os, sys, json, time, re
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(SCRIPT_DIR, 'kb_ppr_baseline.json')

_KB_SKILL = os.path.join(SCRIPT_DIR, '..', 'kb_core')
if _KB_SKILL not in sys.path:
    sys.path.insert(0, _KB_SKILL)
from kb import KB, normalize_code, extract_code

# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

# ── 类别1: 消歧测试 (同一词, 不同语境, PPR应能分离) ──
DISAMBIGUATION_TESTS = [
    # (query, 应偏向的标准码, 不应偏向的标准码/领域)
    ("蜂窝麻面处理", ["GB50204", "GB50666"], []),
    ("混凝土强度等级", ["GB50010", "GBT50107"], []),
    ("防水混凝土抗渗等级", ["GB50108"], []),
    ("砌体结构施工", ["GB50203", "GB50003"], []),
    ("钢结构焊接", ["GB50205", "GB50017"], []),
    ("基坑支护设计", ["JGJ120"], []),
    ("建筑防火设计", ["GB50016"], []),
    ("屋面防水施工", ["GB50207", "GB50345"], []),
]

# ── 类别2: 多跳测试 (查询词不在目标文件正文中, 靠图传播到达) ──
# 验证方法: 检查目标文件是否在 PPR top-10 中
MULTI_HOP_TESTS = [
    # (query, 期望标准码, 查询词中至少有一个不在目标文件标题中的词)
    # 注意: 这些是PPR图传播能到达的路径验证
    ("冷缝处理措施", ["GB50204", "GB50666"]),
    ("植筋锚固深度", ["GB50367", "GB50010"]),
    ("后浇带浇筑时间", ["GB50204", "GB50666"]),
    ("拆模强度要求", ["GB50204", "GB50666"]),
    ("焊缝探伤比例", ["GB50205", "GB50017"]),
    ("土钉墙支护", ["JGJ120"]),
    ("构造柱配筋要求", ["GB50011", "GB50003"]),
]

# ── 类别3: 罕见词桥接 (低频术语 → 通过共现路径找到标准) ──
RARE_TERM_TESTS = [
    ("防碱背涂处理", ["GB50209"]),
    ("EPS换填阻燃要求", []),  # 跨领域查询, 验证至少返回结果
    ("泛碱防治措施", ["GB50209", "JGJ102"]),
    ("碳纤维布加固", ["GB50367"]),
    ("粘钢加固设计", ["GB50367"]),
    ("CFG桩复合地基", ["JGJ79"]),
    ("预应力锚索施工", ["JGJ120"]),
    ("耐火极限要求", ["GB50016"]),
]

# ═══════════════════════════════════════════════════════════════
# 评估函数
# ═══════════════════════════════════════════════════════════════

def resolve_expected(codes):
    resolved = set()
    for c in codes:
        nc = normalize_code(c)
        if nc:
            resolved.add(nc)
            if nc.startswith('GBT'): resolved.add(nc.replace('GBT', 'GB', 1))
            elif nc.startswith('GB') and not nc.startswith('GBT'): resolved.add(nc.replace('GB', 'GBT', 1))
    return resolved

def extract_code_from_result(result):
    if isinstance(result, dict):
        code = extract_code(result.get('file', ''))
        if not code:
            m = re.search(r'(CJJT?\s*\d+)', result.get('file', ''))
            if m: code = normalize_code(m.group())
        if code:
            m = re.match(r'^(.+?)(19[5-9]\d|20[0-9]\d)$', code)
            if m: code = m.group(1)
        return normalize_code(code) if code else None
    return None

def evaluate_disambiguation(kb):
    """评估消歧能力: PPR对相关查询的结果应有明显区分"""
    r = kb._get_resolver()
    # Warm up
    r._ppr_graph_search('混凝土', max_results=1)

    results = {}
    for query, expected, _ in DISAMBIGUATION_TESTS:
        ppr = r._ppr_graph_search(query, max_results=10)
        codes = []
        for rr in ppr:
            c = extract_code_from_result(rr)
            if c: codes.append(c)
        results[query] = {'codes': codes[:10], 'hits': sum(1 for c in codes if c in resolve_expected(expected))}

    # 配对消歧: 对相邻的测试对, 检查结果重叠度
    pairs = []
    for i in range(0, len(DISAMBIGUATION_TESTS), 2):
        if i + 1 < len(DISAMBIGUATION_TESTS):
            q1 = DISAMBIGUATION_TESTS[i][0]
            q2 = DISAMBIGUATION_TESTS[i+1][0]
            c1 = set(results[q1]['codes'])
            c2 = set(results[q2]['codes'])
            if c1 and c2:
                jaccard = len(c1 & c2) / max(len(c1 | c2), 1)
            else:
                jaccard = 1.0 if not c1 and not c2 else 1.0
            pairs.append((q1, q2, jaccard < 0.5))  # 分离度好的话 Jaccard < 0.5

    match_count = sum(1 for v in results.values() if v['hits'] > 0)
    sep_ok = sum(1 for _, _, ok in pairs if ok)
    return {
        'match': round(match_count / max(len(results), 1), 3),
        'separation_ok': sep_ok,
        'separation_total': len(pairs),
        'separation_rate': round(sep_ok / max(len(pairs), 1), 3),
        'details': {q: {'hits': v['hits'], 'top3': v['codes'][:3]} for q, v in results.items()}
    }

def evaluate_multi_hop(kb):
    """评估多跳能力: 期望代码是否在 PPR top-10 中"""
    r = kb._get_resolver()
    results = {}

    for query, expected_codes in MULTI_HOP_TESTS:
        expected = resolve_expected(expected_codes)
        ppr = r._ppr_graph_search(query, max_results=10)
        codes = []
        for rr in ppr:
            c = extract_code_from_result(rr)
            if c: codes.append(c)
        hits = [c for c in codes if c in expected]
        results[query] = {
            'hits': len(hits),
            'rank': codes.index(hits[0]) + 1 if hits else 0,
            'found': len(hits) > 0,
            'top3': codes[:3]
        }

    match_count = sum(1 for v in results.values() if v['found'])
    return {
        'match': round(match_count / max(len(results), 1), 3),
        'details': results
    }

def evaluate_rare_terms(kb):
    """评估罕见词桥接: 低频术语能否找到相关标准"""
    r = kb._get_resolver()

    # 获取术语索引中的低频词列表
    term_idx = r._term_index
    term_counts = {}
    if term_idx:
        idx_data = term_idx.get('index', {})
        for term, entries in idx_data.items():
            term_counts[term] = len(entries) if isinstance(entries, list) else 0

    results = {}
    for query, expected_codes in RARE_TERM_TESTS:
        expected = resolve_expected(expected_codes)
        ppr = r._ppr_graph_search(query, max_results=10)
        codes = []
        for rr in ppr:
            c = extract_code_from_result(rr)
            if c: codes.append(c)

        hits = [c for c in codes if c in expected] if expected else []
        has_results = len(ppr) > 0

        # 找出查询中的罕见词
        import jieba
        tokens = [t for t in jieba.lcut(query) if len(t) >= 2]
        rare = [t for t in tokens if term_counts.get(t, 999) < 5]

        results[query] = {
            'found': len(hits) > 0 if expected else has_results,
            'hits': len(hits),
            'has_results': has_results,
            'rare_terms': rare,
            'top3': codes[:3]
        }

    match_count = sum(1 for v in results.values() if v['found'])
    return {
        'match': round(match_count / max(len(results), 1), 3),
        'details': results
    }

def evaluate_graph_health(kb):
    """评估图结构健康度"""
    r = kb._get_resolver()
    graph = r._load_ppr_graph()
    if not graph:
        return {'loaded': False, 'error': 'Graph not found'}

    edges = graph['edges']
    n_terms = graph['n_terms']
    n_files = graph['n_files']
    total = graph['total']

    # 孤立节点
    has_out_edges = sum(1 for row in edges[:n_terms] if len(row) > 0)
    isolated = n_terms - has_out_edges

    # T-F 边占比
    tf_edges = sum(1 for row in edges[:n_terms] for tgt, _ in row if tgt >= n_terms)
    total_edges = sum(len(row) for row in edges[:n_terms])
    tf_ratio = tf_edges / max(total_edges, 1)

    # 出度分布
    out_degrees = [len(row) for row in edges[:n_terms]]
    import numpy as np
    avg_degree = np.mean(out_degrees)
    median_degree = np.median(out_degrees)
    max_degree = np.max(out_degrees)

    return {
        'loaded': True,
        'total_nodes': int(total),
        'n_terms': int(n_terms),
        'n_files': int(n_files),
        'total_edges': int(total_edges),
        'tf_edges': int(tf_edges),
        'tf_ratio': round(float(tf_ratio), 3),
        'isolated_terms': int(isolated),
        'isolated_pct': round(float(isolated / max(n_terms, 1) * 100), 1),
        'avg_degree': round(float(avg_degree), 1),
        'median_degree': round(float(median_degree), 1),
        'max_degree': int(max_degree),
    }

def evaluate(kb):
    return {
        'disambiguation': evaluate_disambiguation(kb),
        'multi_hop': evaluate_multi_hop(kb),
        'rare_terms': evaluate_rare_terms(kb),
        'graph_health': evaluate_graph_health(kb),
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }

# ═══════════════════════════════════════════════════════════════
# 基线比对
# ═══════════════════════════════════════════════════════════════

THRESHOLDS = {
    'disambiguation.match': 0.05,
    'multi_hop.match': 0.10,
    'rare_terms.match': 0.10,
    'graph_health.tf_ratio': 0.10,
    'graph_health.isolated_pct': 2.0,  # 孤立节点率上升 > 2% → 告警
}

def check_degradation(current, baseline):
    degradations = []

    if current['disambiguation']['match'] < baseline['disambiguation']['match'] - THRESHOLDS['disambiguation.match']:
        degradations.append(f"消歧匹配: {baseline['disambiguation']['match']}→{current['disambiguation']['match']}")

    if current['multi_hop']['match'] < baseline['multi_hop']['match'] - THRESHOLDS['multi_hop.match']:
        degradations.append(f"多跳匹配: {baseline['multi_hop']['match']}→{current['multi_hop']['match']}")

    if current['rare_terms']['match'] < baseline['rare_terms']['match'] - THRESHOLDS['rare_terms.match']:
        degradations.append(f"罕见词: {baseline['rare_terms']['match']}→{current['rare_terms']['match']}")

    gh_c = current['graph_health']
    gh_b = baseline['graph_health']
    if gh_c.get('tf_ratio', 0) < gh_b.get('tf_ratio', 0) - THRESHOLDS['graph_health.tf_ratio']:
        degradations.append(f"T→F比率: {gh_b.get('tf_ratio')}→{gh_c.get('tf_ratio')}")
    if gh_c.get('isolated_pct', 0) > gh_b.get('isolated_pct', 0) + THRESHOLDS['graph_health.isolated_pct']:
        degradations.append(f"孤立节点: {gh_b.get('isolated_pct')}%→{gh_c.get('isolated_pct')}%")

    return degradations, len(degradations) == 0

# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def print_report(result):
    print(f"\n{'='*60}")
    print("PPR 图传播质量报告")
    print(f"{'='*60}")

    d = result['disambiguation']
    print(f"\n消歧测试: {d['match']:.1%} 匹配, {d['separation_ok']}/{d['separation_total']} 对可分离")
    for q, v in d['details'].items():
        codes_s = ','.join(v['top3'])
        print(f"  {'✓' if v['hits']>0 else '✗'} {q[:30]}: {codes_s}")

    mh = result['multi_hop']
    print(f"\n多跳测试: {mh['match']:.1%} 匹配")
    for q, v in mh['details'].items():
        rank_s = f'rank={v["rank"]}' if v['found'] else 'NOT FOUND'
        print(f"  {'✓' if v['found'] else '✗'} {q[:30]}: {rank_s}")

    rt = result['rare_terms']
    print(f"\n罕见词桥接: {rt['match']:.1%} 匹配")
    for q, v in rt['details'].items():
        rare_s = ','.join(v['rare_terms'])
        codes_s = ','.join(v['top3'])
        print(f"  {'✓' if v['found'] else '✗'} {q[:30]}: rare=[{rare_s}] → {codes_s}")

    gh = result['graph_health']
    if gh.get('loaded'):
        print(f"\n图结构健康:")
        print(f"  节点: {gh['n_terms']}词 + {gh['n_files']}文件 = {gh['total_nodes']}")
        print(f"  边: {gh['total_edges']:,} (T→F: {gh['tf_edges']:,}, {gh['tf_ratio']:.1%})")
        print(f"  出度: avg={gh['avg_degree']} med={gh['median_degree']} max={gh['max_degree']}")
        print(f"  孤立词: {gh['isolated_terms']} ({gh['isolated_pct']}%)")
    else:
        print(f"\n图结构健康: 图未加载")

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', action='store_true', help='保存当前结果为基线')
    p.add_argument('--check', action='store_true', help='与基线比对')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    args = p.parse_args()

    sys.stdout.reconfigure(encoding='utf-8')

    kb = KB()
    print('[PPR质量门] 开始评估...')
    t0 = time.time()
    result = evaluate(kb)
    elapsed = time.time() - t0

    if args.json:
        # Filter details for clean JSON
        clean = {
            'disambiguation': {'match': result['disambiguation']['match'],
                              'separation_rate': result['disambiguation']['separation_rate']},
            'multi_hop': {'match': result['multi_hop']['match']},
            'rare_terms': {'match': result['rare_terms']['match']},
            'graph_health': result['graph_health'],
            'timestamp': result['timestamp'],
        }
        print(json.dumps(clean, ensure_ascii=False, indent=2))
    else:
        print_report(result)
        print(f'\n[PPR质量门] 完成 ({elapsed:.0f}s)')

    if args.baseline:
        with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f'基线已保存: {BASELINE_PATH}')

    if args.check:
        if not os.path.exists(BASELINE_PATH):
            print('基线文件不存在, 请先运行 --baseline')
            sys.exit(1)
        with open(BASELINE_PATH, 'r', encoding='utf-8') as f:
            baseline = json.load(f)
        degradations, ok = check_degradation(result, baseline)
        if degradations:
            print(f'\n❌ PPR质量门阻塞 — {len(degradations)} 项退化:')
            for d in degradations:
                print(f'    {d}')
            sys.exit(1)
        else:
            print(f'\n✅ PPR质量门通过 — 无退化')

if __name__ == '__main__':
    main()
