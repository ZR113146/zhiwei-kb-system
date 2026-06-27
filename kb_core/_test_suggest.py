import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
KB = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
si = json.load(open(os.path.join(KB, 'kb_search_index.json'), 'r', encoding='utf-8'))
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
        cache.append({'text': name, 'type': 'standard', 'file': fname})
    for sec in sections:
        h = sec.get('heading', '').strip()
        if h and len(h) >= 2 and h not in seen:
            seen.add(h)
            cache.append({'text': h, 'type': 'clause', 'file': fname})
print(f'Total candidates: {len(cache)}')
for q in ['地面', '混凝土', 'GB50204', '防水平整']:
    matches = [c for c in cache if c['text'].lower().startswith(q.lower())][:4]
    if not matches:
        matches = [c for c in cache if all(t in c['text'].lower() for t in q.lower().split())][:4]
    print(f'\n\"{q}\":')
    for m in matches:
        print(f'  [{m["type"]}] {m["text"]}')
