"""MD导入 kb-mcp + G6一致性 + G7大文件分段
用法: python kb_import.py
"""
import os, json, re, sys
from datetime import datetime
# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
from kb_core.kb import load_config
import kb_core.changelog as changelog; changelog.record(__file__, sys.argv)

_cfg = load_config()
SRC_DIR = _cfg['paths']['work_json']
KB_DIR = _cfg['paths']['kb_md']          # data/index/ (project MD vault)
KB_MD_LIB = _cfg['paths'].get('kb_md_lib', os.path.join(os.path.dirname(__file__), '..', 'data', 'md_lib_v2'))  # MD永久库
MD_MANIFEST = _cfg['paths']['md_manifest']
KB_JSON_DIR = _cfg['paths']['kb_json']
MAX_FILE_KB = 2000
SEGMENT_CHARS = 30000

def load_md_manifest():
    if os.path.exists(MD_MANIFEST):
        return json.load(open(MD_MANIFEST, 'r', encoding='utf-8'))
    return {"_meta": {"updated": "", "source": SRC_DIR}, "imported": {}}

def save_md_manifest(m):
    m['_meta']['updated'] = datetime.now().isoformat()
    with open(MD_MANIFEST, 'w', encoding='utf-8') as f: json.dump(m, f, ensure_ascii=False, indent=2)

def write_to_kb(title, content):
    """写入 kb_md/ 目标（Codex 平台）"""
    import hashlib
    safe = title.replace('/', '_').replace('\\', '_').replace(':', '_')[:60]
    tag = hashlib.md5(title.encode()).hexdigest()[:4] if len(title) > 60 else ''
    tag = f'_{tag}' if tag else ''
    fname = f'{safe}{tag}.md'

    # 目标: Codex 平台 MD vault
    fpath = os.path.join(KB_DIR, fname)
    # 根据文件名推断学科标签
    import re as _re
    code = _re.search(r'((?:GB|JGJ|CJJ|CECS|DB|JTG|TCECS)\s*T?\s*\d+)', title.upper().replace(' ',''))
    tag_suffix = ''
    if code:
        c = code.group(0).replace(' ','')
        if c.startswith('CJJ') or c.startswith('CJ'): tag_suffix = ',市政路桥'
        elif c.startswith('JTG'): tag_suffix = ',市政路桥'
        elif c.startswith('JGJ') or c.startswith('GB'): tag_suffix = ',房屋建筑'
    if '手册' in title or '汇编' in title: tag_suffix += ',工具书'
    yaml_header = f'---\ntitle: "{title}"\nintent: 规范条款查询\nproject: "施工规范知识库"\ntags: [规范,施工,标准{tag_suffix}]\nimported_at: {datetime.now().isoformat()}\n---\n\n'
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(yaml_header + content)

    # 目标2: MD永久库（不含yaml头，保持MinerU原始格式）
    os.makedirs(KB_MD_LIB, exist_ok=True)
    lib_path = os.path.join(KB_MD_LIB, fname)
    with open(lib_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return fpath

def get_norm_id(fname):
    # 规范化: _T → /T (统一分隔符), 然后提取编号前缀+年份 (支持JTG F20格式)
    normalized = fname.replace('_T', '/T')
    m = re.search(r'((?:[A-Z]{2,})(?:\d+)?(?:\/T)?\s*[A-Z]?\d+[\-\.\/]\d+)', normalized)
    return m.group(1).replace(' ', '').replace('/T', 'T') if m else None

def is_dup(norm_id):
    """精确匹配：两边各提取编号后等值比较，避免子串误判（如 GB5020 匹配 GB50209）"""
    if not norm_id: return False
    for f in os.listdir(KB_DIR):
        existing = get_norm_id(f)
        if existing and existing == norm_id:
            return True
    return False

def split_large(fname, content):
    """按字节阈值分段，避免中文文件字节超限但字符未超导致的漏检"""
    if len(content.encode('utf-8')) <= MAX_FILE_KB * 1024:
        return None
    parts = []
    for i in range(0, len(content), SEGMENT_CHARS):
        parts.append((f'{os.path.splitext(fname)[0]}_part{i//SEGMENT_CHARS+1}',
                      content[i:i+SEGMENT_CHARS]))
    print(f'  SPLIT {fname} → {len(parts)}段')
    return parts

def check_content_quality(content, fname):
    """内容质量门槛 — Bigram异常占比检测半页扫描/缺列。
    原理: 用KB训练的条件熵bigram模型检验字符转移，统计训练语料中
         从未出现的字符配对比例。正常文档<0.2%, 半页扫描>1%。
    返回 (passed: bool, reason: str)
    """
    if not content or len(content) < 2:
        return True, 'empty'

    try:
        from kb_bigram_model import check_content_quality as _bigram_check
        return _bigram_check(content, fname)
    except (ImportError, FileNotFoundError):
        from collections import Counter
        import math
        freq = Counter(content)
        total = len(content)
        entropy = -sum((c / total) * math.log2(c / total) for c in freq.values())
        if entropy < 4.5:
            return False, f'内容质量异常: 熵{entropy:.2f} (正常>=5.0)'
        return True, ''


def precheck_mineru_output():
    """MinerU产出初步校验——入库前检查MD文件完整性"""
    md_files = [f for f in os.listdir(SRC_DIR) if f.endswith('.md')]
    if not md_files:
        print('  [预检] SRC_DIR 无MD文件 → 跳过')
        return True

    issues = []
    for fname in md_files:
        fpath = os.path.join(SRC_DIR, fname)
        size = os.path.getsize(fpath)
        if size < 100:  # 小于100字节视为空文件
            issues.append(f'{fname} 文件过小({size}B)')
            continue
        if size > MAX_FILE_KB * 1024 * 3:  # 超过3倍上限
            issues.append(f'{fname} 过大({size/1024:.0f}KB)')
            continue
        # 读前500字符检查内容是否有效
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                head = f.read(500)
            if not head.strip():
                issues.append(f'{fname} 内容为空')
            elif len(head) < 50:
                issues.append(f'{fname} 内容过短({len(head)}字符)')
        except Exception as e:
            issues.append(f'{fname} 读取失败: {e}')

    if issues:
        print(f'  [预检] WARNING: {len(issues)}个文件有问题:')
        for i in issues[:5]:
            print(f'    - {i}')
        return False
    print(f'  [预检] OK: {len(md_files)}个MD文件通过初步校验')
    return True


def consistency_report():
    j = len([f for f in os.listdir(KB_JSON_DIR) if f.endswith('.json') and f != 'manifest.json']) if os.path.isdir(KB_JSON_DIR) else -1
    m = len(load_md_manifest().get('imported', {}))
    k = len([f for f in os.listdir(KB_DIR) if f.endswith('.md')])
    l = len([f for f in os.listdir(KB_MD_LIB) if f.endswith('.md')]) if os.path.isdir(KB_MD_LIB) else -1
    print(f'\nG6 一致性: kb_json={j}, md_manifest={m}, kb_md(rag)={k}, kb_md(lib)={l}')
    if j >= 0 and abs(m - j) > j * 0.1: print('  [WARN] JSON数与MD数不一致')
    if k >= 0 and l >= 0 and k != l: print(f'  [WARN] RAG({k})!=永久库({l})')
    return j, m, k

def import_all():
    # 入库前预检 MinerU 产物
    if not precheck_mineru_output():
        print('[预检] MinerU产物校验未通过，中止导入')
        return -1

    manifest = load_md_manifest()
    imported = set(manifest.get('imported', {}).keys())
    pending = [f for f in sorted(os.listdir(SRC_DIR)) if f.endswith('.md') and f not in imported]
    if not pending: print('无待导入'); return 0
    ok = skip = reject = 0
    for fname in pending:
        fpath = os.path.join(SRC_DIR, fname)
        size_kb = os.path.getsize(fpath) / 1024
        if get_norm_id(fname) and is_dup(get_norm_id(fname)):
            print(f'  DUP {fname}'); skip += 1; continue
        content = open(fpath, 'r', encoding='utf-8').read()

        # 内容质量门槛 — 拦截半页扫描/缺列等提取缺陷
        quality_ok, quality_reason = check_content_quality(content, fname)
        if not quality_ok:
            print(f'  [REJECT] {fname}: {quality_reason}')
            reject += 1; continue
        parts = split_large(fname, content)
        if parts:
            for pt, pc in parts:
                try:
                    kp = write_to_kb(pt, pc)
                    manifest['imported'][f'{fname}#{pt}'] = {'title': pt, 'imported_at': datetime.now().isoformat(), 'kb_path': kp}
                    ok += 1
                except Exception as e: print(f'  ERR {fname}: {e}')
        else:
            try:
                kp = write_to_kb(os.path.splitext(fname)[0], content)
                manifest['imported'][fname] = {'title': os.path.splitext(fname)[0], 'imported_at': datetime.now().isoformat(), 'kb_path': kp}
                print(f'  OK {fname} ({size_kb:.0f}KB)'); ok += 1
            except Exception as e: print(f'  ERR {fname}: {e}')
    save_md_manifest(manifest)
    print(f'\n完成: {ok}成功 {skip}跳过 {reject}拒绝')
    consistency_report()
    return ok

if __name__ == '__main__': import_all()
