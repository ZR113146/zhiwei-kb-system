# -*- coding: utf-8 -*-
"""KB 质量门 — v7.0 统一搜索质量 + PPR 图质量评估

搜索测试: 53 用例, 12 类别, 指标 match_rate/recall_pair/mrr/zero_result_rate
PPR 测试: 消歧(8) + 多跳(7) + 罕见词(8) + 图健康

用法:
  python kb_quality.py                     # 全量评估
  python kb_quality.py --baseline          # 保存基线
  python kb_quality.py --check             # 对比基线, 退化 exit 1
  python kb_quality.py --ppr-only          # 仅 PPR 测试
  python kb_quality.py --search-only       # 仅搜索测试
"""

import os, sys, json, time, re

# Path setup
KB_SKILL = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(KB_SKILL, 'kb_quality_baseline.json')
PPR_BASELINE_PATH = os.path.join(KB_SKILL, 'kb_ppr_baseline.json')

from kb_core.kb import KB, normalize_code, extract_code

# ═══════════════════════════════════════════════════════
# 搜索测试用例 (53 条)
# ═══════════════════════════════════════════════════════

SEARCH_TESTS = [
    # 结构工程 (9)
    ("混凝土结构设计规范", ["GB50010"]),
    ("混凝土强度等级评定标准", ["GBT50107"]),
    ("钢结构设计标准", ["GB50017"]),
    ("砌体结构设计规范", ["GB50003"]),
    ("建筑抗震设计规范", ["GB50011"]),
    ("建筑地基基础设计规范", ["GB50007"]),
    ("建筑结构荷载规范", ["GB50009"]),
    ("地基处理技术规范", ["JGJ79"]),
    # 施工质量验收 (8)
    ("混凝土结构工程施工质量验收规范", ["GB50204"]),
    ("建筑地面工程施工质量验收规范", ["GB50209"]),
    ("建筑装饰装修工程质量验收标准", ["GB50210"]),
    ("建筑电气工程施工质量验收规范", ["GB50303"]),
    ("砌体结构工程施工质量验收规范", ["GB50203"]),
    ("建筑给水排水及采暖工程施工质量验收规范", ["GB50242"]),
    ("通风与空调工程施工质量验收规范", ["GB50243"]),
    ("建筑工程施工质量验收统一标准", ["GB50300"]),
    # 给排水/消防/电气/园林 (7)
    ("建筑给水排水设计标准", ["GB50015"]),
    ("建筑设计防火规范", ["GB50016"]),
    ("自动喷水灭火系统设计规范", ["GB50084"]),
    ("电力工程电缆设计标准", ["GB50217"]),
    ("园林绿化工程施工及验收规范", ["CJJ82"]),
    ("园林绿化养护标准", ["CJJT287"]),
    ("建筑防烟排烟系统技术标准", ["GB51251"]),
    # 基坑/岩土/安全 (5)
    ("建筑基坑支护技术规程", ["JGJ120"]),
    ("建筑桩基技术规范", ["JGJ94"]),
    ("建筑施工安全检查标准", ["JGJ59"]),
    ("施工现场临时用电安全技术规范", ["JGJ46"]),
    ("建筑施工高处作业安全技术规范", ["JGJ80"]),
    # 材料 (4)
    ("建设用砂", ["GBT14684"]),
    ("建设用卵石碎石", ["GBT14685"]),
    ("钢筋混凝土用钢 热轧带肋钢筋", ["GBT1499.2"]),
    ("天然大理石建筑板材", ["GBT19766"]),
    # 口语化模糊 (10)
    ("回填土压实系数要求", ["GB50007", "GB50202"]),
    ("混凝土养护多长时间", ["GB50204", "GB50666"]),
    ("花岗岩铺装防碱背涂", ["GB50209", "JGJ102"]),
    ("外墙保温材料防火要求", ["GB50016", "GBT10801.1"]),
    ("卫生间防水怎么做", ["GB50207", "GB50108"]),
    ("电缆桥架安装要求", ["GB50217", "GB50303"]),
    ("脚手架搭设规范要求", ["JGJ130", "JGJ231"]),
    ("种植土厚度要求", ["CJJ82", "GB55014"]),
    ("施工现场扬尘控制", ["GB12523", "GB16297"]),
    ("基坑监测频率要求", ["JGJ120", "GB50021"]),
    # 口语化 v6.18 (10)
    ("混凝土浇完多久可以拆模板", ["GB50204", "GB50666"]),
    ("构造柱纵筋最小直径要求", ["GB50011", "GB50003"]),
    ("外墙保温怎么防火", ["GB50016"]),
    ("地下室防水怎么做才不会漏水", ["GB50108", "GB50207"]),
    ("钢筋接头怎么错开位置", ["GB50010", "GB50204"]),
    ("楼梯栏杆要多高才符合规范", ["GB50352"]),
    ("大体积混凝土温控措施有哪些", ["GB50496", "GB50204"]),
    ("防火涂料厚度要求多少", ["GB50016", "GB51249"]),
    ("屋面女儿墙最小高度要求", ["GB50352"]),
    ("后浇带什么时候可以浇筑", ["GB50204", "GB50666"]),
]

# 宽松替代答案 (NL 查询的 PPR 跨域补充)
RELAXED_EXPECTED = {
    "钢筋混凝土用钢 热轧带肋钢筋": ["GB50010", "GB50204"],
    "天然大理石建筑板材": ["GB50209", "GB50210"],
    "施工现场扬尘控制": ["GBT50905", "JGJ146"],
    "大体积混凝土温控措施有哪些": ["GB50666", "GB50164"],
    "回弹法检测混凝土强度怎么操作": ["GB50204", "GBT50107"],
    "花岗岩铺装防碱背涂": ["GBT32837", "GB50210"],
    "防火涂料厚度要求多少": ["GB50205", "GB50755"],
    "屋面女儿墙最小高度要求": ["GB50009", "GB50011"],
    "冷缝处理措施有哪些": ["GB50108", "GB50208"],
    "外墙保温材料防火要求": ["GB50411", "GBT50378"],
    "外墙保温怎么防火": ["GB50411", "GBT50378"],
    "钢筋接头怎么错开位置": ["JGJ107", "JGJ18"],
}

# 退化阈值
THRESHOLDS = {
    'match_rate': 0.02,
    'recall_pair': 0.03,
    'mrr': 0.05,
    'zero_result_rate': 0.02,
}

# ═══════════════════════════════════════════════════════
# PPR 测试用例
# ═══════════════════════════════════════════════════════

DISAMBIGUATION_TESTS = [
    ("蜂窝麻面处理", ["GB50204", "GB50666"], []),
    ("混凝土强度等级", ["GB50010", "GBT50107"], []),
    ("防水混凝土抗渗等级", ["GB50108"], []),
    ("砌体结构施工", ["GB50203", "GB50003"], []),
    ("钢结构焊接", ["GB50205", "GB50017"], []),
    ("基坑支护设计", ["JGJ120"], []),
    ("建筑防火设计", ["GB50016"], []),
    ("屋面防水施工", ["GB50207", "GB50345"], []),
]

MULTI_HOP_TESTS = [
    ("冷缝处理措施", ["GB50204", "GB50666"]),
    ("植筋锚固深度", ["GB50367", "GB50010"]),
    ("后浇带浇筑时间", ["GB50204", "GB50666"]),
    ("拆模强度要求", ["GB50204", "GB50666"]),
    ("焊缝探伤比例", ["GB50205", "GB50017"]),
    ("土钉墙支护", ["JGJ120"]),
    ("构造柱配筋要求", ["GB50011", "GB50003"]),
]

RARE_TERM_TESTS = [
    ("防碱背涂处理", ["GB50209"]),
    ("泛碱防治措施", ["GB50209", "JGJ102"]),
    ("碳纤维布加固", ["GB50367"]),
    ("粘钢加固设计", ["GB50367"]),
    ("CFG桩复合地基", ["JGJ79"]),
    ("预应力锚索施工", ["JGJ120"]),
    ("耐火极限要求", ["GB50016"]),
    ("EPS换填阻燃要求", []),
]

# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def _strip_year(code):
    if not code:
        return None
    m = re.match(r'^(.+?)(19[5-9]\d|20[0-9]\d)$', code)
    return m.group(1) if m else code


def _extract_code_from_result(result):
    if isinstance(result, dict):
        explicit_code = result.get('code', '')
        if explicit_code:
            code = normalize_code(explicit_code)
            return _strip_year(code) if code else None
        file_name = result.get('file', '')
    else:
        file_name = result
    m = re.match(r'\[([^\]]+)\]\s*\(vector match\)', file_name)
    if m:
        code = normalize_code(m.group(1))
        return _strip_year(code) if code else None
    code = extract_code(file_name)
    if not code:
        m = re.search(r'(CJJT?\s*\d+)', file_name)
        if m:
            code = normalize_code(m.group())
    if code:
        code = _strip_year(code)
    return code


def _resolve_expected(codes):
    resolved = set()
    for c in codes:
        nc = normalize_code(c)
        resolved.add(nc)
        if nc.startswith('GBT'):
            resolved.add(nc.replace('GBT', 'GB', 1))
        elif nc.startswith('GB') and not nc.startswith('GBT'):
            resolved.add(nc.replace('GB', 'GBT', 1))
    return resolved


# ═══════════════════════════════════════════════════════
# 搜索质量评估
# ═══════════════════════════════════════════════════════

def evaluate_search(kb, vector_weight=0.4, permissive=True):
    """评估搜索质量 → {match_rate, recall_pair, mrr, zero_result_rate, ...}"""
    total_pairs = 0
    hits = 0.0
    reciprocal_ranks = []
    zero_count = 0
    detailed = []

    for query, expected_codes in SEARCH_TESTS:
        expected = _resolve_expected(expected_codes)
        relaxed = _resolve_expected(RELAXED_EXPECTED.get(query, [])) if permissive else set()

        try:
            results = kb.search(query, max_results=10, vector_weight=vector_weight)
        except Exception as e:
            detailed.append({'query': query, 'error': str(e)})
            reciprocal_ranks.append(0)
            continue

        n = len(results)
        if n == 0:
            zero_count += 1
            reciprocal_ranks.append(0)
            detailed.append({'query': query, 'results': [], 'expected': list(expected), 'hit': False})
            continue

        result_codes = []
        for r in results:
            code = _extract_code_from_result(r)
            if code:
                result_codes.append(code)

        # 匹配判断
        matched = False
        match_score = 0
        best_rank = None
        for rank, code in enumerate(result_codes, 1):
            if code in expected:
                matched = True
                match_score = 1.0
                best_rank = rank
                break
            if code in relaxed:
                match_score = 0.5
                best_rank = rank
                matched = True
                break

        if matched:
            reciprocal_ranks.append(1.0 / best_rank)
        else:
            reciprocal_ranks.append(0)

        hits += match_score
        total_pairs += 1 if expected else 0
        detailed.append({
            'query': query, 'top_codes': result_codes[:5],
            'expected': list(expected), 'hit': matched,
            'match_score': match_score, 'rank': best_rank,
        })

    n_nonimg = sum(1 for t in SEARCH_TESTS if not t[0].startswith('image:'))
    match_rate = hits / max(n_nonimg, 1)
    recall_pair = hits / max(total_pairs, 1)
    mrr = sum(reciprocal_ranks) / max(len(reciprocal_ranks), 1)
    zero_rate = zero_count / max(n_nonimg, 1)

    return {
        'match_rate': round(match_rate, 4),
        'recall_pair': round(recall_pair, 4),
        'mrr': round(mrr, 4),
        'zero_result_rate': round(zero_rate, 4),
        'total_queries': len(SEARCH_TESTS),
        'non_image_queries': n_nonimg,
        'detailed': detailed,
    }


# ═══════════════════════════════════════════════════════
# PPR 质量评估
# ═══════════════════════════════════════════════════════

def evaluate_ppr(kb):
    """PPR 四类评估"""
    results = {}

    # 消歧: 不同查询的 top-10 应有明显区分
    disam_hits = 0
    for query, expected, _ in DISAMBIGUATION_TESTS:
        try:
            r = kb.search(query, max_results=10)
            codes = [_extract_code_from_result(x) for x in r if _extract_code_from_result(x)]
            expected_set = _resolve_expected(expected)
            if any(c in expected_set for c in codes):
                disam_hits += 1
        except Exception:
            pass
    results['disambiguation'] = {
        'total': len(DISAMBIGUATION_TESTS),
        'hits': disam_hits,
        'rate': round(disam_hits / max(len(DISAMBIGUATION_TESTS), 1), 4),
    }

    # 多跳: 查询词不在目标文件中, 靠图传播到达
    mh_hits = 0
    for query, expected in MULTI_HOP_TESTS:
        try:
            r = kb.search(query, max_results=10)
            codes = [_extract_code_from_result(x) for x in r if _extract_code_from_result(x)]
            expected_set = _resolve_expected(expected)
            if any(c in expected_set for c in codes):
                mh_hits += 1
        except Exception:
            pass
    results['multi_hop'] = {
        'total': len(MULTI_HOP_TESTS),
        'hits': mh_hits,
        'rate': round(mh_hits / max(len(MULTI_HOP_TESTS), 1), 4),
    }

    # 罕见词: 低频术语通过共现找到标准
    rt_hits = 0
    for query, expected in RARE_TERM_TESTS:
        try:
            r = kb.search(query, max_results=10)
            codes = [_extract_code_from_result(x) for x in r if _extract_code_from_result(x)]
            if expected:
                expected_set = _resolve_expected(expected)
                if any(c in expected_set for c in codes):
                    rt_hits += 1
            else:
                if len(r) > 0:
                    rt_hits += 1
        except Exception:
            pass
    results['rare_terms'] = {
        'total': len(RARE_TERM_TESTS),
        'hits': rt_hits,
        'rate': round(rt_hits / max(len(RARE_TERM_TESTS), 1), 4),
    }

    # 图健康: 加载 PPR 图并检查结构
    try:
        from kb_core.kb_ppr_engine import get_engine
        eng = get_engine()
        stats = eng.get_graph_stats()
        results['graph_health'] = stats or {'error': 'graph not loaded'}
    except Exception as e:
        results['graph_health'] = {'error': str(e)}

    return results


# ═══════════════════════════════════════════════════════
# 基线管理
# ═══════════════════════════════════════════════════════

def save_baseline(kb):
    search_metrics = evaluate_search(kb)
    ppr_metrics = evaluate_ppr(kb)
    baseline = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'search': {k: v for k, v in search_metrics.items() if k != 'detailed'},
        'ppr': ppr_metrics,
    }
    with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)
    print(f'Baseline saved → {BASELINE_PATH}')
    return baseline


def check_degradation(kb):
    if not os.path.exists(BASELINE_PATH):
        print('No baseline found. Run --baseline first.')
        sys.exit(1)

    with open(BASELINE_PATH, 'r', encoding='utf-8') as f:
        baseline = json.load(f)

    current = evaluate_search(kb)
    degraded = []
    passed = []

    for metric in ['match_rate', 'recall_pair', 'mrr', 'zero_result_rate']:
        prev = baseline['search'].get(metric, 0)
        curr = current.get(metric, 0)
        threshold = THRESHOLDS.get(metric, 0.05)
        delta = curr - prev

        if metric == 'zero_result_rate':
            degraded_flag = delta > threshold
        else:
            degraded_flag = delta < -threshold

        status = 'DEGRADED' if degraded_flag else 'OK'
        line = f'  {metric}: {prev:.4f} → {curr:.4f} (Δ={delta:+.4f}, threshold={threshold}) [{status}]'
        print(line)
        if degraded_flag:
            degraded.append(metric)
        else:
            passed.append(metric)

    if degraded:
        print(f'\nFAIL: {len(degraded)} metrics degraded: {degraded}')
        sys.exit(1)
    else:
        print(f'\nPASS: all {len(passed)} metrics within thresholds')


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description='KB Quality Gate v7.0')
    ap.add_argument('--baseline', action='store_true', help='Save current metrics as baseline')
    ap.add_argument('--check', action='store_true', help='Compare against baseline, exit 1 on degradation')
    ap.add_argument('--ppr-only', action='store_true', help='PPR quality only')
    ap.add_argument('--search-only', action='store_true', help='Search quality only')
    ap.add_argument('--vector-weight', type=float, default=0.4, help='Vector boost weight')
    args = ap.parse_args()

    kb = KB()

    if args.baseline:
        save_baseline(kb)
        return

    if args.check:
        check_degradation(kb)
        return

    # Default: full evaluation
    if not args.ppr_only:
        print('=== 搜索质量评估 ===')
        search = evaluate_search(kb, vector_weight=args.vector_weight)
        print(f'  match_rate:       {search["match_rate"]:.4f}')
        print(f'  recall_pair:      {search["recall_pair"]:.4f}')
        print(f'  mrr:              {search["mrr"]:.4f}')
        print(f'  zero_result_rate: {search["zero_result_rate"]:.4f}')
        print(f'  queries:          {search["total_queries"]}')
        print()

    if not args.search_only:
        print('=== PPR 质量评估 ===')
        ppr = evaluate_ppr(kb)
        print(f'  消歧:     {ppr["disambiguation"]["rate"]:.4f} ({ppr["disambiguation"]["hits"]}/{ppr["disambiguation"]["total"]})')
        print(f'  多跳:     {ppr["multi_hop"]["rate"]:.4f} ({ppr["multi_hop"]["hits"]}/{ppr["multi_hop"]["total"]})')
        print(f'  罕见词:   {ppr["rare_terms"]["rate"]:.4f} ({ppr["rare_terms"]["hits"]}/{ppr["rare_terms"]["total"]})')
        gh = ppr.get('graph_health', {})
        if 'error' not in gh:
            print(f'  图健康:   {gh.get("total_nodes", "?")} nodes, {gh.get("edges", "?")} edges, '
                  f'avg_deg={gh.get("avg_out_degree", "?"):.1f}')
        else:
            print(f'  图健康:   ERROR — {gh["error"]}')


if __name__ == '__main__':
    main()
