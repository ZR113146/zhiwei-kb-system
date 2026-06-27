"""KB 三库完整性校验 — JSON/MD/向量 五层比对
用法: python kb_verify_integrity.py [--alert]
五层: 1计数 2命名 3大小 4哈希 5内容
"""
import os, sys, re, json, hashlib, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_KB_DIR = os.path.join(SCRIPT_DIR, '..', 'kb_core')
sys.path.insert(0, _KB_DIR)
from kb import load_config, KB
kb = KB()
import changelog; changelog.record(__file__, sys.argv)

cfg = load_config()
KB_JSON = cfg['paths']['kb_json']
KB_MD = cfg['paths'].get('kb_md_lib', os.path.join(os.path.dirname(KB_JSON), 'kb_md'))
KNOWLEDGE = cfg['paths']['kb_md']
MANIFEST = cfg['paths']['manifest']
ALERT = '--alert' in sys.argv

def alert(msg):
    """弹窗提示用户（Windows）"""
    print(f'[ALERT] {msg}')
    if ALERT:
        try:
            subprocess.run(['msg', os.environ.get('USERNAME', '*'),
                          msg], timeout=5)
        except: pass

def norm_path(p):
    return os.path.normpath(os.path.expanduser(p))

# ---- 使用 kb.py 统一接口做编号提取/存在性检查（与方案编制技能同源）----
from kb import normalize_code, extract_code as _ec
def _std_code(text):
    c = _ec(text)
    return normalize_code(c) if c else None

KB_JSON = norm_path(KB_JSON)
KB_MD = norm_path(KB_MD)
KNOWLEDGE = norm_path(KNOWLEDGE)

checks = {'pass': 0, 'fail': 0, 'warn': 0}
def check(name, cond, detail='', severity='fail'):
    if cond: checks['pass'] += 1; print(f'  [PASS] {name}')
    elif severity == 'warn': checks['warn'] += 1; print(f'  [WARN] {name}: {detail}')
    else: checks['fail'] += 1; print(f'  [FAIL] {name}: {detail}')

print('=' * 60)
print('KB 完整性校验 — 五层比对')
print(f'  JSON: {KB_JSON}')
print(f'  MD:   {KB_MD}')
print(f'  RAG:  {KNOWLEDGE}')
print('=' * 60)

# ================================================================
# L1: 存在性层 — 用 kb.check() 批量验证（与方案编制同源）
# ================================================================
print('\n--- L1: 存在性层 (kb.check) ---')

if os.path.exists(MANIFEST):
    with open(MANIFEST, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    all_entries = manifest.get('standards', {})
else:
    all_entries = {}

# 提取所有有效编号
manifest_codes = set()
no_code = []
for name, fname in all_entries.items():
    c = _std_code(name) or _std_code(fname)
    if c: manifest_codes.add(c)
    else: no_code.append(name[:40])

# 用 kb.check() 批量验证（与 construction-plan-writer 同源）
results = kb.check(*list(manifest_codes)) if manifest_codes else {}
in_kb = sum(1 for v in results.values() if v)
not_in_kb = sum(1 for v in results.values() if not v)
match_pct = in_kb * 100 // len(manifest_codes) if manifest_codes else 0

md_total = len([f for f in os.listdir(KB_MD) if f.endswith('.md')])
knowledge_all = os.listdir(KNOWLEDGE)
knowledge_stds = [f for f in knowledge_all if f.endswith('.md')
                  and not f.startswith('_seg') and '手册' not in f]

check(f'manifest编号: {len(manifest_codes)} | kb.check: {in_kb} IN / {not_in_kb} NOT ({match_pct}%)',
      match_pct >= 90,
      f'{not_in_kb} not found: {[c for c,v in sorted(results.items()) if not v][:5]}',
      'warn' if match_pct >= 90 else 'fail')
check(f'非标准条目(手册/指南): {len(no_code)}', True)
check(f'MD库: {md_total} | RAG: {len(knowledge_stds)}', True)

# L2: 命名层 — kb.exists() 替代文件名比对
print('\n--- L2: 命名层 (kb.exists) ---')
missing_md = []
for name, fname in all_entries.items():
    c = _std_code(name) or _std_code(fname)
    if not c: continue
    if not kb.exists(c):
        missing_md.append(f'{name[:40]}({c})')

total_with_code = len(manifest_codes)
matched = total_with_code - len(missing_md)
pct = matched * 100 // total_with_code if total_with_code else 0
check(f'kb.exists匹配: {matched}/{total_with_code} ({pct}%)',
      pct >= 90,
      f'{len(missing_md)} not found: {missing_md[:5]}',
      'warn' if pct >= 90 else 'fail')

# 反向检查
missing_rag = []
for f in os.listdir(KB_MD):
    if f.endswith('.md') and f not in knowledge_all:
        base = os.path.splitext(f)[0]
        if not any(base in kf or kf in base for kf in knowledge_all):
            missing_rag.append(f[:60])
check(f'MD→RAG反向: {len(missing_rag)}/' + str(md_total),
      len(missing_rag) <= 5, f'{len(missing_rag)} missing: {missing_rag[:5]}',
      'warn' if len(missing_rag) <= 10 else 'fail')

md_files = [f for f in os.listdir(KB_MD) if f.endswith('.md')]

# L3: 大小层 — 同文件 data/index vs data/md_lib_v2 大小一致
# ================================================================
def _yaml_header_size(fpath):
    """读取 data/index 文件的 YAML 头字节数（无头则返回0）"""
    try:
        with open(fpath, 'rb') as fh:
            first = fh.read(4)
            if first == b'---\n' or first == b'---\r':
                rest = fh.read()
                end = rest.find(b'\n---')
                if end != -1:
                    return 4 + end + 4  # "---\n" + YAML内容 + "\n---"
    except OSError:
        pass
    return 0

print('\n--- L3: 大小层 ---')

size_mismatches = []
size_sample = 0
for f in md_files[:20]:  # 抽检前20个
    if f not in knowledge_all:
        continue
    size_sample += 1
    s_md = os.path.getsize(os.path.join(KB_MD, f))
    s_rag_raw = os.path.getsize(os.path.join(KNOWLEDGE, f))
    yaml_size = _yaml_header_size(os.path.join(KNOWLEDGE, f))
    s_rag = s_rag_raw - yaml_size  # 去掉YAML头后比大小
    diff_pct = abs(s_md - s_rag) / max(s_md, 1) * 100
    if diff_pct > 1:  # 1%差异视为不一致
        size_mismatches.append((f, s_md, s_rag, diff_pct))

check(f'大小一致性(抽{size_sample}个): {size_sample-len(size_mismatches)}/{size_sample}',
      len(size_mismatches) == 0,
      f'{len(size_mismatches)} mismatches: {[(f, f"{p:.1f}%") for f,_,_,p in size_mismatches[:3]]}',
      'warn')

# ================================================================
# L4: 哈希层 — SHA256 剥离YAML头后比较内容 (data/index 带YAML, kb_md 不带)
# ================================================================
print('\n--- L4: 哈希层(SHA256) ---')

def _strip_yaml(content_bytes):
    """去掉原文件的 YAML frontmatter，只比实际内容"""
    text = content_bytes.decode('utf-8', errors='replace')
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            text = text[end + 3:].lstrip('\n\r')
    return text.encode('utf-8')

hash_mismatches = []
hash_sample = 0
for f in md_files[:20]:
    if f not in knowledge_all:
        continue
    hash_sample += 1
    with open(os.path.join(KB_MD, f), 'rb') as fh:
        h_md = hashlib.sha256(fh.read()).hexdigest()
    with open(os.path.join(KNOWLEDGE, f), 'rb') as fh:
        h_rag = hashlib.sha256(_strip_yaml(fh.read())).hexdigest()
    if h_md != h_rag:
        hash_mismatches.append(f)

check(f'哈希一致性(抽{hash_sample}个): {hash_sample-len(hash_mismatches)}/{hash_sample}',
      len(hash_mismatches) == 0,
      f'tampered: {hash_mismatches[:3]}' if hash_mismatches else '',
      'fail' if len(hash_mismatches) > 0 else 'pass')

# ================================================================
# L5: 内容层 — 段落数/行数一致性
# ================================================================
print('\n--- L5: 内容层(段落/行数) ---')

content_mismatches = []
content_sample = 0
for f in md_files[:15]:
    if f not in knowledge_all:
        continue
    content_sample += 1
    p_md = os.path.join(KB_MD, f)
    p_rag = os.path.join(KNOWLEDGE, f)

    with open(p_md, 'r', encoding='utf-8', errors='replace') as fh:
        lines_md = len(fh.readlines())
    with open(p_rag, 'r', encoding='utf-8', errors='replace') as fh:
        lines_rag = len(fh.readlines())

    diff_pct = abs(lines_md - lines_rag) / max(lines_md, 1) * 100
    if diff_pct > 5:  # 5%行数差异
        content_mismatches.append((f, lines_md, lines_rag, diff_pct))

check(f'内容一致性(抽{content_sample}个): {content_sample-len(content_mismatches)}/{content_sample}',
      len(content_mismatches) == 0,
      f'{len(content_mismatches)} diffs' if content_mismatches else '',
      'warn')

# ================================================================
# 汇总 + 弹窗
# ================================================================
print('\n' + '=' * 60)
total = checks['pass'] + checks['fail'] + checks['warn']
print(f'完整性: {checks["pass"]}/{total} 通过 ({checks["fail"]}失败 {checks["warn"]}警告)')

if checks['fail'] > 0:
    alert(f'KB完整性校验发现{checks["fail"]}项严重问题,请检查')
    print('[FAIL] KB 数据可能已损坏——请运行 kb_rollback 或重新入库')
    sys.exit(1)
elif checks['warn'] > 0:
    print(f'[WARN] {checks["warn"]}项警告——建议手动复核')
    sys.exit(0)
else:
    print('[PASS] 三库完整一致')
    sys.exit(0)
