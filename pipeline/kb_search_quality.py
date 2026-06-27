#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""搜索质量门 — 53 用例评估 + 基线比对 + 退化告警

用法:
  python kb_search_quality.py                    # 评估当前搜索质量
  python kb_search_quality.py --baseline         # 将当前结果存为基线
  python kb_search_quality.py --check            # 比基线, 退化则 exit 1

Phase D 自动调用 (--check 模式), 退化时阻塞 Phase D 完成。

基线文件: kb_search_baseline.json (与脚本同目录)
"""

import os, sys, json, time, re
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(SCRIPT_DIR, 'kb_search_baseline.json')

_KB_SKILL = os.path.join(SCRIPT_DIR, '..', 'kb_core')
if _KB_SKILL not in sys.path:
    sys.path.insert(0, _KB_SKILL)
from kb import KB, normalize_code, extract_code


# ============================================================
# 测试用例 (与评估保持一致)
# ============================================================
TEST_CASES = [
    # ═══ v6.23: 匹配当前KB(33标准/113文件) — 原名查询 ═══
    ("混凝土结构设计规范", ["GB50010"]),
    ("钢结构设计标准", ["GB50017"]),
    ("建筑抗震设计规范", ["GB50011"]),
    ("建筑地基基础设计规范", ["GB50007"]),
    ("建筑结构荷载规范", ["GB50009"]),
    ("地基处理技术规范", ["JGJ79"]),
    ("混凝土结构工程施工质量验收规范", ["GB50204"]),
    ("通风与空调工程施工质量验收规范", ["GB50243"]),
    ("建筑给水排水设计标准", ["GB50015"]),
    ("给水排水管道工程施工及验收规范", ["GB50268"]),
    ("室外排水设计标准", ["GB50014"]),
    ("建筑设计防火规范", ["GB50016"]),
    ("建筑基坑支护技术规程", ["JGJ120"]),
    ("建筑桩基技术规范", ["JGJ94"]),
    ("岩土工程勘察规范", ["GB50021"]),
    ("建筑施工模板安全技术规范", ["JGJ162"]),
    ("地下防水工程质量验收规范", ["GB50208"]),
    ("建筑节能工程施工质量验收标准", ["GB50411"]),
    ("建设工程工程量清单计价规范", ["GB50500"]),
    ("建筑防火通用规范", ["GB55037"]),
    ("钢筋焊接及验收规程", ["JGJ18"]),
    ("建筑机械使用安全技术规程", ["JGJ33"]),
    ("钢结构工程施工质量验收标准", ["GB50205"]),
    ("钢结构工程施工规范", ["GB50755"]),
    # ═══ 编号查询 ═══
    ("GB50204-2015", ["GB50204"]),
    ("GB50010", ["GB50010"]),
    ("CJJ 37", ["CJJ37"]),
    ("TCECS 20011", ["TCECS20011"]),
    # ═══ 口语化模糊查询 (过滤后保留) ═══
    ("回填土压实系数要求", ["GB50007"]),
    ("混凝土养护多长时间", ["GB50204", "GB50666"]),
    ("外墙保温材料防火要求", ["GB50016"]),
    ("基坑监测频率要求", ["JGJ120", "GB50021"]),
    ("混凝土浇完多久可以拆模板", ["GB50204", "GB50666"]),
    ("构造柱纵筋最小直径要求", ["GB50011"]),
    ("外墙保温怎么防火", ["GB50016"]),
    ("钢筋接头怎么错开位置", ["GB50010", "GB50204"]),
    ("回填土要压实到什么程度才算合格", ["GB50007"]),
    ("大体积混凝土温控措施有哪些", ["GB50204"]),
    ("后浇带什么时候可以浇筑", ["GB50204", "GB50666"]),
    ("植筋锚固深度怎么确定", ["GB50010"]),
    ("冷缝处理措施有哪些", ["GB50204", "GB50666"]),
    ("排水管道坡度最小是多少", ["GB50268", "GB50015"]),
    ("钢结构焊缝探伤比例要求", ["GB50205", "GB50017"]),
    ("打桩要打到什么深度才合格", ["JGJ94", "GB50007"]),
    ("模板拆除时的混凝土强度要求", ["GB50204", "GB50666"]),
    # ═══ v6.23 新增: 条款直通车测试 ═══
    ("GB50204 5.3", ["GB50204"]),
    ("GB50010 8.3", ["GB50010"]),
    ("GB50666 6.4", ["GB50666"]),
    # ═══ v6.18: 图片查询 10条 ═══
    ("image:构造柱配筋详图", []),
    ("image:焊缝节点详图", []),
    ("image:防水层构造图", []),
    ("image:基础钢筋布置图", []),
    ("image:预应力张拉端构造", []),
    ("image:模板支撑体系图", []),
    ("image:砌体墙构造详图", []),
    ("image:桩基础构造图", []),
    ("image:钢结构连接节点", []),
    ("image:混凝土配合比", []),
]

# v6.20: 宽松匹配 — NL查询的"可接受"替代答案
# PPR 图传播发现的相关但不同标准, 每个计 0.5 分 (而非严格匹配的 1.0 分)
# 这些替代码是 PPR 通过图传播找到的, 与查询主题相关但跨越了原始标注的边界
RELAXED_EXPECTED = {
    # 材料/产品查询 → PPR 找到相关施工/验收标准
    "钢筋混凝土用钢 热轧带肋钢筋": ["GB50010", "GB50204"],
    "天然大理石建筑板材": ["GB50209", "GB50210"],
    # 跨域查询 → PPR 桥接到环境/绿色建筑
    "施工现场扬尘控制": ["GBT50905", "JGJ146"],
    # 罕见概念 → PPR 找到相关技术标准
    "大体积混凝土温控措施有哪些": ["GB50666", "GB50164"],
    "回弹法检测混凝土强度怎么操作": ["GB50204", "GBT50107"],
    # 表面处理/防护 → 多个标准覆盖
    "花岗岩铺装防碱背涂": ["GBT32837", "GB50210"],
    "防火涂料厚度要求多少": ["GB50205", "GB50755"],
    # 结构构件 → 荷载/抗震相关标准
    "屋面女儿墙最小高度要求": ["GB50009", "GB50011"],
    # 施工缝 → 防水/地下工程
    "冷缝处理措施有哪些": ["GB50108", "GB50208"],
    # 外墙 → 节能/绿色建筑
    "外墙保温材料防火要求": ["GB50411", "GBT50378"],
    "外墙保温怎么防火": ["GB50411", "GBT50378"],
    # 钢筋连接 → 机械连接/焊接
    "钢筋接头怎么错开位置": ["JGJ107", "JGJ18"],
}

# 退化阈值 (绝对值变化)
THRESHOLDS = {
    'match_rate': 0.02,       # 匹配率掉 >2% → 告警
    'recall_pair': 0.03,      # 对级召回掉 >3% → 告警
    'mrr': 0.05,              # MRR 掉 >5% → 告警
    'zero_result_rate': 0.02, # 零结果率升 >2% → 告警
}


def strip_year(code):
    if not code:
        return None
    m = re.match(r'^(.+?)(19[5-9]\d|20[0-9]\d)$', code)
    return m.group(1) if m else code


def extract_code_from_result(result):
    # v6.18: 支持图片搜索结果的显式 code 字段
    if isinstance(result, dict):
        explicit_code = result.get('code', '')
        if explicit_code:
            code = normalize_code(explicit_code)
            return strip_year(code) if code else None
        file_name = result.get('file', '')
    else:
        file_name = result
    m = re.match(r'\[([^\]]+)\]\s*\(vector match\)', file_name)
    if m:
        code = normalize_code(m.group(1))
        return strip_year(code) if code else None
    code = extract_code(file_name)
    if not code:
        m = re.search(r'(CJJT?\s*\d+)', file_name)
        if m:
            code = normalize_code(m.group())
    if code:
        code = strip_year(code)
    return code


def resolve_expected(codes):
    resolved = set()
    for c in codes:
        nc = normalize_code(c)
        resolved.add(nc)
        if nc.startswith('GBT'):
            resolved.add(nc.replace('GBT', 'GB', 1))
        elif nc.startswith('GB') and not nc.startswith('GBT'):
            resolved.add(nc.replace('GB', 'GBT', 1))
    return resolved


def evaluate(kb, vector_weight=0.4, permissive=False):
    """返回 {match_rate, recall_pair, mrr, zero_result_rate, ...}
    permissive=True: NL查询的宽松替代码计 0.5 分"""
    total_pairs = 0
    hits = 0.0
    reciprocal_ranks = []
    match_count = 0.0
    zero_count = 0
    n_nonimg = 0
    detailed = []

    for query, expected_codes in TEST_CASES:
        expected = resolve_expected(expected_codes)
        results = kb.search(query, max_results=10, vector_weight=vector_weight)
        is_img = query.startswith('image:')

        if not results:
            zero_count += 1

        result_codes = []
        for r in results:
            code = extract_code_from_result(r)
            result_codes.append(normalize_code(code) if code else None)

        # Strict matching
        query_hits = 0.0
        strict_hit = False
        for i, rc in enumerate(result_codes):
            if rc and rc in expected:
                query_hits += 1.0
                strict_hit = True
                if query_hits >= 0.5:
                    reciprocal_ranks.append(1.0 / (i + 1))
                    break
        else:
            # v6.20: permissive matching — check relaxed expected codes
            if permissive and query in RELAXED_EXPECTED:
                relaxed = resolve_expected(RELAXED_EXPECTED[query])
                for i, rc in enumerate(result_codes):
                    if rc and rc in relaxed:
                        query_hits += 0.5  # Half credit for relaxed matches
                        if query_hits >= 0.5 and not strict_hit:
                            reciprocal_ranks.append(1.0 / (i + 1) * 0.5)
                        break
            if query_hits == 0:
                reciprocal_ranks.append(0)

        if query_hits > 0:
            match_count += 1.0

        if not is_img:
            n_nonimg += 1
            total_pairs += len(expected_codes)
            hits += query_hits

        # v6.18: 来源分布统计
        sources = {'heading': 0, 'bm25_body': 0, 'sentence_vector': 0, 'term_hit': 0}
        for r in results:
            src = r.get('_source', '')
            if src in sources:
                sources[src] += 1
            elif not src:
                sources['heading'] += 1

        detailed.append({
            'query': query,
            'expected': list(expected_codes),
            'hits': query_hits,
            'total': len(expected_codes),
            'num_results': len(results),
            'sources': sources,
        })

    n = len(TEST_CASES)
    nonimg_n = max(n_nonimg, 1)
    return {
        'match_rate': round(match_count / nonimg_n, 4),
        'recall_pair': round(hits / max(total_pairs, 1), 4),
        'mrr': round(sum(rr for i, rr in enumerate(reciprocal_ranks) if not TEST_CASES[i][0].startswith('image:')) / nonimg_n, 4),
        'zero_result_rate': round(zero_count / n, 4),
        'total_queries': n,
        'total_pairs': total_pairs,
        'hits': hits,
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }


def check_degradation(current, baseline, thresholds=THRESHOLDS):
    """比对基线, 返回 (退化列表, 是否全部通过)"""
    degradations = []
    for key, threshold in thresholds.items():
        cur = current.get(key, 0)
        base = baseline.get(key, 0)
        delta = cur - base
        # 对于 '好' 指标 (match_rate, recall, mrr): 下降是退化
        # 对于 '坏' 指标 (zero_result_rate): 上升是退化
        if key == 'zero_result_rate':
            if delta > threshold:
                degradations.append(f'{key}: {base:.2%}→{cur:.2%} (+{delta:.2%}, 阈值{threshold:.0%})')
        else:
            if delta < -threshold:
                degradations.append(f'{key}: {base:.2%}→{cur:.2%} ({delta:.2%}, 阈值{threshold:.0%})')

    return degradations, len(degradations) == 0


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', action='store_true', help='保存当前结果为基线')
    p.add_argument('--check', action='store_true', help='与基线比对, 退化则 exit 1')
    p.add_argument('--json', action='store_true', help='输出 JSON 格式')
    p.add_argument('--permissive', action='store_true', help='v6.20: NL查询允许宽松替代码 (0.5分)')
    args = p.parse_args()

    sys.stdout.reconfigure(encoding='utf-8')

    kb = KB()
    print(f'[质量门] 开始评估 ({len(TEST_CASES)} 查询)...')
    t0 = time.time()
    result = evaluate(kb, vector_weight=0.4, permissive=args.permissive)
    elapsed = time.time() - t0
    print(f'[质量门] 完成 ({elapsed:.0f}s)')

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f'  Match Rate:  {result["match_rate"]:.1%}')
        print(f'  Recall(对级): {result["recall_pair"]:.1%} ({result["hits"]}/{result["total_pairs"]})')
        print(f'  MRR:         {result["mrr"]:.1%}')
        print(f'  零结果率:    {result["zero_result_rate"]:.1%}')

    if args.baseline:
        with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f'\n基线已保存: {BASELINE_PATH}')
        return

    if args.check:
        if not os.path.exists(BASELINE_PATH):
            print(f'\n无基线文件, 自动创建: {BASELINE_PATH}')
            with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            return

        with open(BASELINE_PATH, 'r', encoding='utf-8') as f:
            baseline = json.load(f)

        degradations, ok = check_degradation(result, baseline)

        print(f'\n基线 ({baseline.get("timestamp","?")}):')
        print(f'  Match Rate:  {baseline["match_rate"]:.1%}')
        print(f'  Recall(对级): {baseline["recall_pair"]:.1%}')
        print(f'  MRR:         {baseline["mrr"]:.1%}')
        print(f'  零结果率:    {baseline["zero_result_rate"]:.1%}')

        if ok:
            print('\n✅ 质量门通过 — 无退化')
            # 每次通过时更新基线 (保持基线为最新已知良好状态)
            with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            sys.exit(0)
        else:
            print(f'\n❌ 质量门阻塞 — {len(degradations)} 项退化:')
            for d in degradations:
                print(f'    {d}')
            sys.exit(1)


if __name__ == '__main__':
    main()
