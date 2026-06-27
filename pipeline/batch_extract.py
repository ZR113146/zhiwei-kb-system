"""批量 MinerU 提取 + 分段重命名 + G2/G3/G4防护
用法: python batch_extract.py --all [--workers N] | --retry-failed | --dry <分册名>
"""
import os, re, subprocess, sys, threading, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
if _KB_DIR not in sys.path:
    sys.path.insert(0, _KB_DIR)
from kb import load_config
import changelog; changelog.record(__file__, sys.argv)

_cfg = load_config()
STAGING = _cfg['paths']['staging']
OUT_DIR = _cfg['paths']['work_json']
MINERU_EXE = _cfg['paths']['mineru_exe']
_rename_lock, _print_lock = threading.Lock(), threading.Lock()
FAILED_LOG = os.path.join(os.path.dirname(__file__), 'batch_failed.json')
MAX_RETRIES, RETRY_DELAY = 3, 10
JSON_MIN_SIZE, MD_MIN_LINES = 500, 10

def check_pdf_valid(pdf_path):
    try:
        from pypdf import PdfReader
        r = PdfReader(pdf_path)
        if r.is_encrypted: return False, 0, 'PDF加密'
        p = len(r.pages)
        return (True, p, '') if p > 0 else (False, 0, '页数为0')
    except ImportError: return False, 0, 'pypdf未安装,无法校验PDF'
    except Exception as e: return False, 0, str(e)[:100]

def validate_outputs(fname, md_only=False):
    jp = os.path.join(OUT_DIR, fname.replace('.pdf', '.json'))
    mp = os.path.join(OUT_DIR, fname.replace('.pdf', '.md'))
    j_ok = (not md_only) and os.path.exists(jp) and os.path.getsize(jp) >= JSON_MIN_SIZE
    if not j_ok and os.path.exists(jp): os.remove(jp)
    if os.path.exists(mp):
        try:
            if len(open(mp, 'r', encoding='utf-8').readlines()) < MD_MIN_LINES:
                os.remove(mp)
        except (UnicodeDecodeError, OSError):
            # 编码损坏或权限问题 → 删除无效文件
            os.remove(mp)
    return j_ok, os.path.exists(mp)

def load_failed():
    return json.load(open(FAILED_LOG, 'r', encoding='utf-8')) if os.path.exists(FAILED_LOG) else []

def save_failed(entries):
    with open(FAILED_LOG, 'w', encoding='utf-8') as f: json.dump(entries, f, ensure_ascii=False, indent=2)

def record_failed(fname, seg_num, err_msg):
    entries = load_failed()
    if not any(e['fname'] == fname and e['seg_num'] == seg_num for e in entries):
        entries.append({'fname': fname, 'seg_num': seg_num, 'error': err_msg, 'time': time.strftime('%Y-%m-%dT%H:%M:%S')})
        save_failed(entries)

def group_chunks(pdf_dir):
    groups = {}
    for fname in sorted(os.listdir(pdf_dir)):
        if not fname.endswith('.pdf'): continue
        m = re.search(r'([A-Z]+[\s\/]*\d+[\-\.\/]\d+)', fname)
        key = m.group(1).replace(' ', '') if m else (re.search(r'第(\S+册)', fname) or [None, fname[:40]])[1]
        m2 = re.search(r'_p(\d{4})-(\d{4})', fname)
        seg_num = int(m2.group(1)) // 100 + 1 if m2 else 0
        path = os.path.join(pdf_dir, fname)
        groups.setdefault(key, []).append((seg_num, fname, path, os.path.getsize(path) / (1024*1024)))
    for k in groups: groups[k].sort(key=lambda x: x[0])
    return groups

def extract_one(pdf_path, timeout=1800):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = subprocess.run([MINERU_EXE, 'extract', pdf_path, '-o', OUT_DIR, '-f', 'json,md', '--timeout', str(timeout), '--model', 'vlm'],
                               capture_output=True, timeout=timeout + 120)
            if r.returncode == 0: return True, ''
            if attempt < MAX_RETRIES: time.sleep(RETRY_DELAY)
        except subprocess.TimeoutExpired:
            if attempt < MAX_RETRIES: time.sleep(RETRY_DELAY)
    return False, f'FAIL after {MAX_RETRIES} retries'

def rename_outputs(fname, seg_num):
    targets = {'json': f'_seg{seg_num}_{fname.replace(".pdf", ".json")}',
               'md': f'_seg{seg_num}_{fname.replace(".pdf", ".md")}'}
    renamed = 0
    for ext, target in targets.items():
        orig = os.path.join(OUT_DIR, fname.replace('.pdf', f'.{ext}'))
        if os.path.exists(orig): os.rename(orig, os.path.join(OUT_DIR, target)); renamed += 1
    if renamed < 2:
        with _rename_lock:
            for ext in ['json', 'md']:
                newest = None
                for fn in os.listdir(OUT_DIR):
                    if not fn.startswith('_seg') and fn.endswith(f'.{ext}'):
                        fp = os.path.join(OUT_DIR, fn)
                        if newest is None or os.path.getmtime(fp) > os.path.getmtime(newest): newest = fp
                if newest: os.rename(newest, os.path.join(OUT_DIR, targets[ext])); renamed += 1
    return renamed

def extract_one_chunk(seg_num, fname, path, size_mb):
    check = os.path.join(OUT_DIR, f'_seg{seg_num}_{fname.replace(".pdf", ".json")}')
    if os.path.exists(check): return True, True, 'SKIP'
    valid, pages, err = check_pdf_valid(path)
    if not valid: record_failed(fname, seg_num, f'PDF预检: {err}'); return False, False, f'PDF_INVALID'
    success, err_msg = extract_one(path)
    if not success: record_failed(fname, seg_num, err_msg[:200]); return False, False, 'FAIL'
    j_ok, m_ok = validate_outputs(fname)
    if not m_ok: record_failed(fname, seg_num, f'校验失败 json:{j_ok} md:{m_ok}'); return False, False, 'EMPTY'
    rename_outputs(fname, seg_num)
    with _print_lock: print(f'  [{seg_num}] {fname} OK')
    return True, False, 'OK'

def retry_failed():
    entries = load_failed()
    if not entries: print('无失败记录'); return
    print(f'重试 {len(entries)} 个...')
    for e in entries:
        p = os.path.join(STAGING, e['fname'])
        if not os.path.exists(p): continue
        extract_one_chunk(e['seg_num'], e['fname'], p, os.path.getsize(p)/(1024*1024))

def extract_all(max_workers=20):
    # 新 session 开始，清空上次残留的失败记录
    if os.path.exists(FAILED_LOG):
        os.remove(FAILED_LOG)

    groups = group_chunks(STAGING)
    tasks = []
    for chunks in groups.values():
        for seg, fn, p, s in chunks: tasks.append((seg, fn, p, s))
    print(f'扫描: {len(groups)}组, {len(tasks)}块')
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(extract_one_chunk, *t): t for t in tasks}
        for fut in as_completed(futures):
            try:
                r, sk, _ = fut.result()
                if sk: skip += 1
                elif r: ok += 1
                else: fail += 1
            except: fail += 1
    print(f'完成: {ok}成功 {skip}跳过 {fail}失败')
    return fail

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('volume', nargs='?')
    p.add_argument('--all', action='store_true')
    p.add_argument('--workers', type=int, default=20)
    p.add_argument('--retry-failed', action='store_true')
    p.add_argument('--dry', help='干跑')
    args = p.parse_args()
    if args.retry_failed: retry_failed()
    elif args.all:
        fail = extract_all(args.workers)
        if fail > 0:
            print(f'\n{fail} 个分块提取失败 (已记录到 batch_failed.json)，管线继续')
            print('  使用 --retry-failed 可重试失败文件')
    elif args.dry:
        for k, chunks in group_chunks(STAGING).items():
            if args.dry in k:
                print(f'{k} ({len(chunks)}块)')
                for seg, fn, p, s in chunks:
                    v, pages, e = check_pdf_valid(p)
                    print(f'  [{seg}] {fn} {s:.1f}MB {pages}页 {"OK" if v else e}')
    else: p.print_help()

if __name__ == '__main__': main()
