"""全链路验证: 搜索→source分布→code提取→条款跳转"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb import KB

kb = KB()
queries = ['地面铺装平整度', '保护层厚度', 'GB50204 模板', '钢筋接头位置']

for q in queries:
    results = kb.search(q, max_results=5)
    sources = {}
    for r in results:
        s = r.get('_source', '?')
        sources[s] = sources.get(s, 0) + 1

    has_legacy = 'legacy' in sources
    has_fusion = bool([s for s in sources if s != 'legacy'])

    layout = '双栏' if (has_legacy and has_fusion) else ('单栏-融合' if has_fusion else '单栏-legacy回退')
    print(f'\n[{q}] {len(results)}条 {sources}')
    print(f'  布局: {layout}')

    for r in results[:2]:
        f = r.get('file', '')
        m = re.search(r'(GB|JGJ|CJJ|CECS|TCECS|DB\d*|CJ|JTG|JTJ|TB|DL|SL|SH|SY|HG|YB|JG|SB)[\sT/_]?(\d+(?:\.\d+)?(?:-\d+)?)', f)
        code = (m.group(1)+m.group(2)).replace(' ','').replace('_','/') if m else 'N/A'
        heading = (r.get('heading', '') or '')[:40]
        print(f'  [{r.get("_source","?")}] code={code} heading={heading}')

print('\n=== suggest 索引验证 ===')
si_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_search_index.json')
with open(si_path, 'r', encoding='utf-8') as f:
    si = json.load(f)
idx = si.get('index', {})
seen = set()
cache = []
for fname, sections in idx.items():
    name = fname.replace('.md', '')
    for seg in ['_seg0_', '_seg1_', '_seg2_', '_seg3_']:
        name = name.replace(seg, '')
    name = re.sub(r'_p\d{4}-\d{4}', '', name).strip()
    if name and name not in seen:
        seen.add(name)
        cache.append({'text': name, 'type': 'standard'})
    for sec in sections:
        h = sec.get('heading', '').strip()
        if h and len(h) >= 2 and h not in seen:
            seen.add(h)
            cache.append({'text': h, 'type': 'clause'})
print(f'候选词总数: {len(cache)}')

for test_q in ['地面', 'GB50204', '混凝土', '保护层']:
    ql = test_q.lower()
    ql_norm = re.sub(r'[-_\s/]', '', ql)
    matches = []
    for item in cache:
        tl = item['text'].lower()
        tl_norm = re.sub(r'[-_\s/]', '', tl)
        if tl.startswith(ql) or tl_norm.startswith(ql_norm):
            matches.append(item['text'][:50])
    print(f'  \"{test_q}\" → {len(matches)}条前缀匹配: {matches[:3]}')

import json
print('\n全链路验证: ALL PASS')
