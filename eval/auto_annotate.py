# -*- coding: utf-8 -*-
"""自动生成真值标注 — 从搜索日志 + 领域知识 + search 交叉校验"""

import json, sys, os, re
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_LOG = os.path.join(ROOT, 'pipeline', 'kb_search_log.jsonl')
OUTPUT = os.path.join(ROOT, 'eval', 'truth_queries_v2.jsonl')

CODE_PAT = re.compile(r'(?:GB|JGJ|CJJ|CECS|TCECS|DB|JTG)[\sT/]?\d+', re.IGNORECASE)

# === 领域知识映射表 ===
DOMAIN_MAP = {
    '混凝土养护|混凝土浇完|混凝土强度|大体积混凝土|混凝土温控': {
        'outcome': 'support', 'stds': ['GB50204', 'GB50666', 'GB50164'],
        'clauses': {'GB50204': '7.4.3', 'GB50666': '8.5.2', 'GB50164': '6.7.5'},
        'type': 'clause_support'
    },
    '混凝土结构工程施工质量验收规范': {
        'outcome': 'support', 'stds': ['GB50204'],
        'clauses': {'GB50204': '1.0.1'},
        'type': 'standard_name'
    },
    '混凝土结构设计规范': {
        'outcome': 'support', 'stds': ['GB50010'],
        'clauses': {'GB50010': '1.0.1'},
        'type': 'standard_name'
    },
    '建筑地基基础设计规范': {
        'outcome': 'support', 'stds': ['GB50007'],
        'clauses': {'GB50007': '1.0.1'},
        'type': 'standard_name'
    },
    '回填土压实|压实系数|回填土|压实度': {
        'outcome': 'support', 'stds': ['GB50202', 'JGJ79', 'GB50007'],
        'clauses': {'GB50202': '6.1.5', 'JGJ79': '4.2.1'},
        'type': 'parameter_clause'
    },
    '钢筋接头|钢筋连接|钢筋机械连接': {
        'outcome': 'support', 'stds': ['JGJ107', 'GB50666', 'GB50204'],
        'clauses': {'JGJ107': '4.0.1', 'GB50666': '5.4.1', 'GB50204': '5.4.1'},
        'type': 'clause_support'
    },
    '钢筋保护层厚度|保护层厚度': {
        'outcome': 'support', 'stds': ['GB50010', 'GB50204'],
        'clauses': {'GB50010': '8.2.1', 'GB50204': '5.3.1'},
        'type': 'parameter_clause'
    },
    '模板拆除|拆模板|模板拆模|模板拆除强度': {
        'outcome': 'support', 'stds': ['GB50666', 'JGJ162', 'GB50204'],
        'clauses': {'GB50666': '4.5.2', 'JGJ162': '7.5.3', 'GB50204': '4.3.1'},
        'type': 'parameter_clause'
    },
    '后浇带|施工缝|后浇带什么时候': {
        'outcome': 'support', 'stds': ['GB50666', 'GB50108'],
        'clauses': {'GB50666': '8.3.1', 'GB50108': '5.1.1'},
        'type': 'clause_support'
    },
    '基坑支护|基坑开挖|深基坑': {
        'outcome': 'support', 'stds': ['JGJ120', 'GB50202'],
        'clauses': {'JGJ120': '3.1.1', 'GB50202': '3.1.1'},
        'type': 'clause_support'
    },
    '脚手架|扣件式|钢管脚手架': {
        'outcome': 'support', 'stds': ['JGJ130', 'GB55023'],
        'clauses': {'JGJ130': '6.1.1'},
        'type': 'clause_support'
    },
    '外墙保温|外墙保温材料|外保温|外墙外保温': {
        'outcome': 'support', 'stds': ['JGJ144', 'GB50411'],
        'clauses': {'JGJ144': '4.0.1'},
        'type': 'clause_support'
    },
    '防水卷材|屋面防水|地下室防水|防水施工|防水层': {
        'outcome': 'support', 'stds': ['GB50345', 'GB50207', 'GB50108'],
        'clauses': {'GB50345': '4.1.1', 'GB50207': '4.1.1', 'GB50108': '4.1.1'},
        'type': 'clause_support'
    },
    '给排水|给水管道|排水管道|给水排水': {
        'outcome': 'support', 'stds': ['GB50268', 'GB50242', 'GB50015'],
        'clauses': {'GB50268': '4.1.1', 'GB50242': '3.1.1', 'GB50015': '1.0.1'},
        'type': 'clause_support'
    },
    '建筑给水排水设计标准': {
        'outcome': 'support', 'stds': ['GB50015'],
        'clauses': {'GB50015': '1.0.1'},
        'type': 'standard_name'
    },
    '砌体|砌筑|砖砌|砂浆强度': {
        'outcome': 'support', 'stds': ['GB50203', 'GB50003'],
        'clauses': {'GB50203': '3.0.1', 'GB50003': '3.2.1'},
        'type': 'clause_support'
    },
    '钢结构|焊缝|高强螺栓|钢结构焊接|超声波探伤': {
        'outcome': 'support', 'stds': ['GB50205', 'GB50755', 'GB50017'],
        'clauses': {'GB50205': '5.1.1', 'GB50755': '4.1.1', 'GB50017': '7.1.1'},
        'type': 'clause_support'
    },
    '钢结构设计标准': {
        'outcome': 'support', 'stds': ['GB50017'],
        'clauses': {'GB50017': '1.0.1'},
        'type': 'standard_name'
    },
    '地基处理|CFG桩|换填|强夯|复合地基': {
        'outcome': 'support', 'stds': ['JGJ79', 'GB50202', 'GB50007'],
        'clauses': {'JGJ79': '4.1.1', 'GB50202': '4.1.1'},
        'type': 'parameter_clause'
    },
    '装饰装修|抹灰|涂饰|吊顶|门窗安装': {
        'outcome': 'support', 'stds': ['GB50210'],
        'clauses': {'GB50210': '4.1.1'},
        'type': 'clause_support'
    },
    '地面铺装|地面工程|地坪|铺装地面|建筑地面': {
        'outcome': 'support', 'stds': ['GB50209'],
        'clauses': {'GB50209': '5.1.1'},
        'type': 'clause_support'
    },
    '园林绿化|苗木|种植土|花坛|绿化养护': {
        'outcome': 'support', 'stds': ['CJJT287', 'GB55014'],
        'clauses': {'CJJT287': '5.1.1', 'GB55014': '3.1.1'},
        'type': 'clause_support'
    },
    '电气|电缆|配电|照明|防雷|桥架|供配电': {
        'outcome': 'support', 'stds': ['GB50303', 'GB50057'],
        'clauses': {'GB50303': '3.1.1', 'GB50057': '4.1.1'},
        'type': 'clause_support'
    },
    '暖通|通风|空调|风管|防排烟|通风空调': {
        'outcome': 'support', 'stds': ['GB50243', 'GB50736'],
        'clauses': {'GB50243': '4.1.1'},
        'type': 'clause_support'
    },
    '通风与空调工程施工质量验收规范': {
        'outcome': 'support', 'stds': ['GB50243'],
        'clauses': {'GB50243': '1.0.1'},
        'type': 'standard_name'
    },
    '抗震|抗震设计|地震作用': {
        'outcome': 'support', 'stds': ['GB50011'],
        'clauses': {'GB50011': '3.1.1'},
        'type': 'clause_support'
    },
    '安全|高处作业|临时用电|塔吊|起重|施工安全|施工用电': {
        'outcome': 'support', 'stds': ['JGJ46', 'JGJ80', 'JGJ33'],
        'clauses': {'JGJ46': '3.1.1', 'JGJ80': '3.0.1', 'JGJ33': '4.1.1'},
        'type': 'clause_support'
    },
    '建筑机械使用安全技术规程': {
        'outcome': 'support', 'stds': ['JGJ33'],
        'clauses': {'JGJ33': '1.0.1'},
        'type': 'standard_name'
    },
    '建筑施工模板安全技术规范': {
        'outcome': 'support', 'stds': ['JGJ162'],
        'clauses': {'JGJ162': '1.0.1'},
        'type': 'standard_name'
    },
    '质量验收|检验批|质量检验|竣工验收': {
        'outcome': 'support', 'stds': ['GB50300'],
        'clauses': {'GB50300': '3.0.1'},
        'type': 'clause_support'
    },
    '地下防水工程质量验收规范': {
        'outcome': 'support', 'stds': ['GB50208'],
        'clauses': {'GB50208': '1.0.1'},
        'type': 'standard_name'
    },
    '建筑节能工程施工质量验收标准': {
        'outcome': 'support', 'stds': ['GB50411'],
        'clauses': {'GB50411': '1.0.1'},
        'type': 'standard_name'
    },
    '钢结构工程施工质量验收标准|钢结构工程施工规范': {
        'outcome': 'support', 'stds': ['GB50205', 'GB50755'],
        'clauses': {'GB50205': '1.0.1', 'GB50755': '1.0.1'},
        'type': 'standard_name'
    },
    '噪声|扬尘|环境噪声|施工噪声': {
        'outcome': 'support', 'stds': ['GB12523'],
        'clauses': {'GB12523': '4.1.1'},
        'type': 'parameter_clause'
    },
    '模板安装|模板支撑|高大模板|模板工程': {
        'outcome': 'support', 'stds': ['JGJ162', 'GB50666'],
        'clauses': {'JGJ162': '6.1.1', 'GB50666': '4.4.1'},
        'type': 'clause_support'
    },
    '植筋锚固|植筋|锚固长度': {
        'outcome': 'support', 'stds': ['GB50367', 'JGJ145'],
        'clauses': {'GB50367': '12.1.1'},
        'type': 'parameter_clause'
    },
    '后浇带|施工缝|后浇带什么时候': {
        'outcome': 'support', 'stds': ['GB50666', 'GB50108'],
        'clauses': {'GB50666': '8.3.1', 'GB50108': '5.1.1'},
        'type': 'clause_support'
    },
    '地下连续墙|地连墙|地下墙': {
        'outcome': 'support', 'stds': ['JGJT303', 'GB50202'],
        'clauses': {'JGJT303': '4.1.1'},
        'type': 'clause_support'
    },
    '预应力|预应力混凝土': {
        'outcome': 'support', 'stds': ['GB50666', 'GB50204'],
        'clauses': {'GB50666': '6.1.1', 'GB50204': '6.1.1'},
        'type': 'clause_support'
    },
    '钢结构设计|混凝土结构设计|地基基础设计|抗震设计': {
        'outcome': 'review', 'stds': [],
        'type': 'broad_technical'
    },
    '怎么|如何|什么|哪些|多少|怎样|为何|为什么': {
        'outcome': 'review', 'stds': [],
        'type': 'broad_technical'
    },
}


def main():
    # Load search log
    queries = Counter()
    with open(SEARCH_LOG, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = e.get('q', '').strip()
            if q:
                queries[q] += 1

    candidates = []
    for q, count in queries.most_common(200):
        cn = len([c for c in q if '一' <= c <= '鿿'])
        if count < 5:
            continue
        if cn < 4:
            continue
        if CODE_PAT.search(q):
            continue
        candidates.append((q, count))
        if len(candidates) >= 120:
            break

    print(f'候选查询: {len(candidates)}')

    # Auto-annotate
    annotations = []
    for q, count in candidates:
        matched = False
        for pattern, info in DOMAIN_MAP.items():
            if re.search(pattern, q):
                required = []
                for sc in info.get('stds', [])[:2]:
                    cl = info['clauses'].get(sc, '')
                    required.append({
                        'standard_code': sc,
                        'clause_no': cl or '',
                        'clause_type': 'normative',
                    })
                entry = {
                    'id': f'truth_v2_{len(annotations) + 1:04d}',
                    'query': q,
                    'query_type': info.get('type', 'clause_support'),
                    'expected_outcome': info.get('outcome', 'support'),
                    'required_clauses': required,
                    'forbidden_hits': [],
                    'acceptable_alternatives': [],
                    'difficulty': 'medium',
                    'review_status': 'auto_annotated',
                    'source_query_count': count,
                }
                annotations.append(entry)
                matched = True
                break
        if not matched:
            annotations.append({
                'id': f'truth_v2_{len(annotations) + 1:04d}',
                'query': q,
                'query_type': 'broad_technical',
                'expected_outcome': 'review',
                'required_clauses': [],
                'forbidden_hits': [],
                'difficulty': 'hard',
                'review_status': 'auto_annotated_unmatched',
                'source_query_count': count,
            })

    # Cross-validate: for top 40, run actual search and verify
    from kb_core.kb import KB
    from kb_core.code_norm import extract_standard
    kb = KB()
    cross_ok = 0
    cross_fail = 0
    for a in annotations[:40]:
        if not a.get('required_clauses'):
            continue
        try:
            results = kb.search(a['query'], max_results=5)
            expected_codes = {c['standard_code'] for c in a['required_clauses']}
            found_codes = set()
            for r in results:
                info = extract_standard(r.get('file', ''))
                if info and info.get('standard_code'):
                    found_codes.add(info['standard_code'])
            overlap = expected_codes & found_codes
            a['cross_validation'] = {
                'expected': list(expected_codes),
                'found': list(found_codes),
                'overlap': list(overlap),
            }
            if overlap:
                cross_ok += 1
            else:
                cross_fail += 1
                a['cross_validation']['warning'] = 'expected not in top-5, review needed'
        except Exception as exc:
            a['cross_validation'] = {'error': str(exc)}
            cross_fail += 1

    print(f'交叉校验: {cross_ok}/{cross_ok + cross_fail} 预期标准在 top-5 中')
    if cross_fail > 0:
        print(f'  需人工复核: {cross_fail} 条')
        for a in annotations[:40]:
            if a.get('cross_validation', {}).get('warning'):
                print(f'    {a["query"][:40]}: expected={a["cross_validation"]["expected"]} found={a["cross_validation"]["found"]}')

    # Write output
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        for a in annotations:
            f.write(json.dumps(a, ensure_ascii=False) + '\n')

    # Stats
    support = sum(1 for a in annotations if a['expected_outcome'] == 'support')
    refuse = sum(1 for a in annotations if a['expected_outcome'] == 'refuse')
    review = sum(1 for a in annotations if a['expected_outcome'] == 'review')
    print(f'\n总标注: {len(annotations)}')
    print(f'  support={support}  refuse={refuse}  review={review}')
    types = Counter(a['query_type'] for a in annotations)
    print(f'  类型: {dict(types)}')
    print(f'\n输出: {OUTPUT}')


if __name__ == '__main__':
    main()
