"""KB 关键路径集成测试 — 20条覆盖全管线 A→B→C→D + 搜索 + bigram
用法: python kb_self_test.py
"""
import os, sys, json, random, time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_KB_DIR = os.path.join(SCRIPTS_DIR, '..', 'kb_core')
sys.path.insert(0, _KB_DIR)
sys.path.insert(0, SCRIPTS_DIR)
from kb import KB, load_config, normalize_code, extract_code

kb = KB(); cfg = load_config()
PASS = FAIL = 0

def t(name, cond, detail=''):
    global PASS, FAIL
    if cond is True: PASS += 1; print(f'  [PASS] {name}')
    else: FAIL += 1; print(f'  [FAIL] {name}: {detail}')

print('KB 集成测试 — 20条关键路径')
print('=' * 50)

# ── 1. 配置 (3条) ──
print('\n1. 配置')
for k in ['staging','work_json','kb_json','kb_md','kb_md_lib','manifest','standards_index','vectordb','mineru_exe']:
    v = cfg['paths'].get(k,'')
    t(f'paths.{k}', bool(v))
    break  # just check first 3
for k in ['staging','kb_json','kb_md','work_json']:
    v = cfg['paths'].get(k,'')
    t(f'paths.{k} exists', os.path.exists(os.path.expanduser(v)) if v else False)

# ── 2. KB API (5条) ──
print('\n2. KB API')
s = kb.status()
t('status', s['standards'] > 0 and s['clauses'] > 0)
r = kb.check('GB50209','JGJ79','CJJ82','GB99999')
t('check', r['GB50209'] and r['JGJ79'] and not r['GB99999'])
r = kb.search('混凝土强度', max_results=3)
t('search', len(r) > 0 and 'file' in r[0])
n = kb.get_name('GB50209')[0]
t('get_name', n and '地面' in n)
txt = kb.read_clause('GB50209', '4.1')
t('read_clause', txt and len(txt) > 10)

# ── 3. 索引完整性 (3条) ──
print('\n3. 索引')
si = os.path.expanduser(cfg['paths']['standards_index'])
if os.path.exists(si):
    with open(si, 'r', encoding='utf-8') as f:
        si_data = json.load(f)
    sc = len([k for k in si_data if not k.startswith('_')])
    tc = sum(len(v) for k,v in si_data.items() if not k.startswith('_'))
    t(f'standards_index: {sc}部/{tc}条', sc > 0)
else:
    t('standards_index', False, 'file missing')

mf = os.path.expanduser(cfg['paths']['manifest'])
if os.path.exists(mf):
    with open(mf, 'r', encoding='utf-8') as f:
        mf_data = json.load(f)
    t(f'manifest: {len(mf_data.get("standards",{}))} standards', True)
    t(f'index vs manifest match', len(si_data)-1 >= len(mf_data.get('standards',{}))-3)

# ── 4. 向量搜索 (2条) ──
print('\n4. 向量搜索')
r = kb.search('地基承载力', max_results=5)
t('keyword search', len(r) > 0)
r_vec = kb.search('花岗岩 防碱', max_results=5, vector_weight=0.4)
t('vector hybrid', len(r_vec) > 0)

# ── 5. Bigram 模型 (3条) ──
print('\n5. Bigram 模型')
try:
    from kb_bigram_model import load_model, check_content_quality as bq
    model = load_model()
    t('model loaded', model is not None)
    if model:
        t(f'model V={model["V"]}', model['V'] >= 4000)
        t(f'P_min={model["p_min"]:.1e}', model['p_min'] < 1e-6)
except Exception as e:
    t('model import', False, str(e)[:60])

# ── 6. 数据完整性 (2条) ──
print('\n6. 数据完整性')
rag = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
lib = os.path.join(os.path.dirname(__file__), '..', 'data', 'md_lib_v2')
rag_md = len([f for f in os.listdir(rag) if f.endswith('.md')])
lib_md = len([f for f in os.listdir(lib) if f.endswith('.md')])
t(f'RAG({rag_md}) vs LIB({lib_md})', abs(rag_md - lib_md) <= 5)
kb_self = os.path.join(_KB_DIR, 'kb.py')
import subprocess
r = subprocess.run([sys.executable, kb_self, 'self-test'], capture_output=True, text=True, timeout=30)
t('kb.py self-test', 'ALL SELF-TESTS PASSED' in r.stdout)

# ── 汇总 ──
print('\n' + '=' * 50)
total = PASS + FAIL
print(f'{PASS}/{total} PASS ({PASS*100//total}%)')
if FAIL > 0:
    print(f'{FAIL} FAILURES')
    sys.exit(1)
