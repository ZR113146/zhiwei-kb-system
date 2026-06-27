"""端到端验证 — 抽查新规范条款可检索性
用法: python kb_e2e_verify.py [--sample 3] [--standard GB50009]
"""
import os, json, sys, random, re, subprocess
random.seed(42)  # 确定性抽样，保证CI可复现
# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
if _KB_DIR not in sys.path:
    sys.path.insert(0, _KB_DIR)
from kb import load_config
import changelog; changelog.record(__file__, sys.argv)

_cfg = load_config()
KB_JSON_DIR = _cfg['paths']['kb_json']
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

def get_recent_standards(n=30):
    mp = os.path.join(KB_JSON_DIR, 'manifest.json')
    if not os.path.exists(mp): return []
    m = json.load(open(mp, 'r', encoding='utf-8')).get('standards', {})
    items = []
    for name, jf in m.items():
        p = os.path.join(KB_JSON_DIR, jf)
        if os.path.exists(p): items.append((name, jf, os.path.getmtime(p)))
    items.sort(key=lambda x: x[2], reverse=True)
    return items[:n]

def sample_clauses(std_name, jf, n=3):
    p = os.path.join(KB_JSON_DIR, jf)
    if not os.path.exists(p): return []
    data = json.load(open(p, 'r', encoding='utf-8'))
    clauses = data if isinstance(data, list) else data.get('clauses', data.get('content', []))
    if not isinstance(clauses, list): return []
    meaningful = [(c, (c.get('text','') if isinstance(c,dict) else str(c))[:80]) for c in clauses if len(str(c)) > 20]
    return random.sample(meaningful, min(n, len(meaningful)))

def search_kw(keyword):
    idx_script = os.path.join(SCRIPTS_DIR, 'kb_search_index.py')
    try:
        r = subprocess.run([sys.executable, idx_script, keyword], capture_output=True, text=True, timeout=30, cwd=SCRIPTS_DIR)
        return r.stdout[:500]
    except: return '(搜索异常)'

def verify(std_name, jf, n=3):
    print(f'\n{"─"*50}\n[E2E] {std_name}\n   文件: {jf}')
    clauses = sample_clauses(std_name, jf, n)
    if not clauses: print('   [WARN] 无条款'); return 0, 0
    ok = 0
    for i, (clause, excerpt) in enumerate(clauses):
        words = re.findall(r'[\u4e00-\u9fff]{2,}', excerpt)
        kw = ' '.join(words[:3]) if len(words) >= 2 else excerpt[:20]
        print(f'\n   条款{i+1}: {excerpt}...\n   搜索: "{kw}"')
        r = search_kw(kw)
        if r and '无结果' not in r and '(搜索异常' not in r:
            lines = len([l for l in r.split('\n') if l.strip()])
            print(f'   [OK] 命中 ({lines}行)'); ok += 1
        else: print(f'   [FAIL] 未命中')
    return ok, len(clauses)

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--sample', type=int, default=3)
    p.add_argument('--standard'); p.add_argument('--standards', type=int, default=3)
    args = p.parse_args()
    if args.standard:
        targets = [(n,j,m) for n,j,m in get_recent_standards() if args.standard in n or args.standard in j]
        if not targets: print(f'未找到: {args.standard}'); return
        targets = targets[:1]
    else:
        targets = get_recent_standards()[:args.standards]
    if not targets: print('无可验证规范'); return
    print(f'验证: {len(targets)}规范 x{args.sample}条款')
    tok, tot = 0, 0
    for n, j, _ in targets:
        ok, cnt = verify(n, j, args.sample); tok += ok; tot += cnt
    print(f'\n{"="*50}\n{tok}/{tot} 可检索')
    if tot > 0:
        rate = tok/tot
        print(f'[PASS] 通过 ({rate:.0%})' if rate >= 0.8 else f'[WARN] 部分通过 ({rate:.0%})' if rate >= 0.5 else f'[FAIL] 未通过 ({rate:.0%})')

if __name__ == '__main__': main()
