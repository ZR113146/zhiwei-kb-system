# -*- coding: utf-8 -*-
"""第0步: 从 KB 真源生成归一化黄金真相表 (只读, 零代码风险)。

诚实锚定 (回应"该用 std.samr.gov.cn 外部权威, 而非 KB 自证"):
  - external_verified=True: 该标准在 standard_status.json 里有 samr/openstd
    evidence (evidence_source 含 openstd.samr.gov.cn, 含 evidence_url)。
    此时期望 canonical 来自 evidence 的 official_code (外部权威码), 不再用
    KB 入库时的 std_code (那可能是归一化错的、自证循环)。
  - external_verified=False: 无 samr evidence。期望仍用 KB std_code, 但明确
    标注"未外部核对" — v1/v2 对账时这类条目的"自洽"只证明入库/检索一致,
    不证明对规范界正确。不混作真·真相。

本环境 fetch 不了 samr (网络策略拦), 故全量外部核对由 sync_status_from_samr.py
在能访问 samr 的环境跑; 跑完 status 全量带 evidence 后, 本表自然全量 external_verified。

字段:
  raw, current_canonical (v1), v2_canonical, std_code (KB入库码),
  expected_canonical (外部有据时=samr official; 否则=std_code, 标自证),
  family, external_verified, evidence_url, is_no_code, v1_consistent, v2_consistent
"""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kb_core.code_norm import normalize_code as v1, official_code, _normalize_v2 as v2

ci = json.load(open(os.path.join(ROOT, 'data', 'kb_json', 'kb_clause_index.json'), encoding='utf-8'))
status = json.load(open(os.path.join(ROOT, 'data', 'kb_json', 'standard_status.json'), encoding='utf-8'))
stds = status.get('standards', {})

def has_samr_evidence(rec):
    es = str(rec.get('evidence_source', '')) + ' ' + str(rec.get('evidence_url', ''))
    return 'samr' in es.lower() or 'openstd' in es.lower()

CODE_PREFIX_RE = re.compile(r'(?:GB|JGJ|CJJ|TCECS|CECS|CJ|JC|DB|JTG|RISN)(?=[\s_/\-]|$)', re.IGNORECASE)
FAM_PREFIX = {'GB', 'JGJ', 'CJJ', 'TCECS', 'CECS', 'CJ', 'JC', 'DB', 'JTG', 'RISN'}

OUT = []
ext_verified = 0
for fn, d in ci['index'].items():
    sc = d.get('std_code', '')
    if not sc:
        continue
    raw = re.sub(r'^_seg\d+', '', fn).replace('.md', '')
    raw = re.sub(r'_p\d{4}-\d{4}$', '', raw).strip().lstrip('_')
    cur = v1(raw)
    v2c = v2(raw)
    rec = stds.get(sc, {})
    ext = has_samr_evidence(rec)
    if ext:
        ext_verified += 1
        # 期望 canonical = samr 官方码归一 (用 v1 把 official_code 归一, 因 v1 是当前生产)
        expected = v1(rec.get('official_code', '')) or sc
    else:
        expected = sc  # 自证锚 (未外部核对)
    m = re.match(r'([A-Z]+)', sc)
    fam = m.group(1) if m else '未知'
    has_code = bool(CODE_PREFIX_RE.search(raw))
    is_no_code = not has_code
    OUT.append({
        'raw': raw,
        'current_canonical': cur,           # v1
        'v2_canonical': v2c,
        'std_code': sc,
        'expected_canonical': expected,
        'family': fam,
        'external_verified': ext,
        'evidence_url': rec.get('evidence_url', ''),
        'is_no_code': is_no_code,
        'v1_consistent': is_no_code or (cur == expected),
        'v2_consistent': is_no_code or (v2c == expected),
    })

out_path = os.path.join(ROOT, 'eval', 'golden_norm_truth.jsonl')
with open(out_path, 'w', encoding='utf-8') as f:
    for r in OUT:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

coded = [r for r in OUT if not r['is_no_code']]
ext = [r for r in coded if r['external_verified']]
selfv = [r for r in coded if not r['external_verified']]
print(f'生成 {len(OUT)} 条 (有码 {len(coded)} / 无码 {len(OUT)-len(coded)})')
print(f'外部权威已核对 (samr evidence): {len(ext)} 条')
print(f'未外部核对 (自证锚): {len(selfv)} 条')
print()
print('=== 外部已核对子集: v1/v2 与 samr 期望一致性 ===')
v1e = sum(1 for r in ext if r['v1_consistent'])
v2e = sum(1 for r in ext if r['v2_consistent'])
print(f'  v1 一致 {v1e}/{len(ext)}; v2 一致 {v2e}/{len(ext)}')
for r in ext:
    flag = '' if r['v2_consistent'] else '  <-- v2不一致'
    print(f"   {r['std_code']:12} expected={r['expected_canonical']:12} v1={r['current_canonical']:12} v2={r['v2_canonical']:12}{flag}")
print()
print('=== 未核对子集 (自证): v1 vs v2 回退检测 ===')
regress = [r for r in selfv if r['v1_consistent'] and not r['v2_consistent']]
print(f'  v2 回退 (v1自洽v2不自洽): {len(regress)}')
for r in regress[:8]:
    print(f"   {r['raw'][:34]:36} v1={r['current_canonical']:12} v2={r['v2_canonical']:12} std={r['std_code']:12}")
