"""Phase-Locked Pipeline Orchestrator — 4-Phase 知识库入库编排器
session.json 唯一真相源，幂等可重入。

用法:
  python pipeline_orchestrator.py "PDF目录"      # 全流程
  python pipeline_orchestrator.py --resume       # 断点恢复
  python pipeline_orchestrator.py --phase b      # 单Phase
"""
import os, sys, json, time, shutil, subprocess, re
from datetime import datetime
from pathlib import Path
# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
from kb_core.kb import load_config
import kb_core.changelog as changelog; changelog.record(__file__, sys.argv)
from pypdf import PdfReader
from contextlib import redirect_stderr

def _read_pdf(path):
    with redirect_stderr(open(os.devnull, 'w')):
        return PdfReader(path)

_cfg = load_config()
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
KB_NEW_DIR = os.path.dirname(_cfg['paths']['work_json'])
STAGING = _cfg['paths']['staging']
WORK_JSON = _cfg['paths']['work_json']
KB_DIR = _cfg['paths']['kb_md']
KB_MD_LIB = _cfg['paths'].get('kb_md_lib', os.path.join(os.path.dirname(__file__), '..', 'data', 'md_lib_v2'))
KB_JSON_DIR = _cfg['paths']['kb_json']
MD_MANIFEST = _cfg['paths']['md_manifest']
SESSION_DIR = os.path.join(KB_NEW_DIR, 'sessions')
COMPLETED_DIR = os.path.join(SESSION_DIR, 'completed')
LOCK_FILE = os.path.join(KB_NEW_DIR, '.pipeline.lock')
SPLITTER = os.path.join(SCRIPTS_DIR, 'split_pdfs.py')

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(COMPLETED_DIR, exist_ok=True)
os.makedirs(STAGING, exist_ok=True)


class Session:
    def __init__(self, path=None):
        self.path = path or os.path.join(SESSION_DIR, 'session.json')
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            return json.load(open(self.path, 'r', encoding='utf-8'))
        # session.json 不存在（可能已被重命名），扫描最近的 session_*.json
        if self.path.endswith('session.json'):
            candidates = sorted(
                [f for f in os.listdir(os.path.dirname(self.path))
                 if f.startswith('session_') and f.endswith('.json')],
                reverse=True)
            if candidates:
                self.path = os.path.join(os.path.dirname(self.path), candidates[0])
                return json.load(open(self.path, 'r', encoding='utf-8'))
        return None

    def create(self, source_dir, files_info):
        sid = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.data = {'session_id': sid, 'phase': 'A',
                     'started_at': datetime.now().isoformat(), 'updated_at': datetime.now().isoformat(),
                     'source_dir': source_dir, 'files': files_info,
                     'phase_a': {'status': 'pending'}, 'phase_b': {'status': 'pending'},
                     'phase_c': {'status': 'pending'}, 'phase_d': {'status': 'pending'},
                     'errors': [], '_lock_pid': os.getpid()}
        self._save()
        self.path = os.path.join(SESSION_DIR, f'session_{sid}.json')
        os.rename(os.path.join(SESSION_DIR, 'session.json'), self.path)
        return self

    def _save(self):
        self.data['updated_at'] = datetime.now().isoformat()
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def update_phase(self, phase, **kwargs):
        key = f'phase_{phase.lower()}'
        self.data.setdefault(key, {}).update(kwargs)
        self._save()

    def archive(self):
        dst = os.path.join(COMPLETED_DIR, os.path.basename(self.path))
        shutil.move(self.path, dst)
        self.path = dst

    def get_imported_count(self):
        return self.data.get('files', {}).get('new', 0) + self.data.get('files', {}).get('updated', 0)


def _pid_alive(pid):
    """检查进程是否存活（跨平台，不依赖psutil）"""
    try:
        os.kill(pid, 0)  # 信号0只检测进程存在，不发送信号
        return True
    except (OSError, ProcessLookupError):
        return False

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            pid = int(open(LOCK_FILE).read().strip())
        except (ValueError, FileNotFoundError):
            pid = None
        if pid and _pid_alive(pid):
            return False, f'另一个入库进程运行中 (PID {pid})'
        # 僵尸锁（进程已死）→ 自动清除
        try:
            os.remove(LOCK_FILE)
            print(f'[LOCK] 清除僵尸锁 (PID {pid if pid else "?"})')
        except OSError:
            pass
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    return True, ''

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            try:
                if int(open(LOCK_FILE).read().strip()) == os.getpid():
                    os.remove(LOCK_FILE)
            except (ValueError, FileNotFoundError):
                # 锁文件已被其他进程清理或损坏 → 尝试删除
                try:
                    os.remove(LOCK_FILE)
                except OSError:
                    pass
    except OSError:
        pass


def extract_code(fname):
    """从文件名提取规范编号 -> 规范形 (canonical)。委托 code_norm 唯一真源
    (旧内联正则处理不了入库下划线形式且各处不一致)。"""
    from kb_core.code_norm import extract_standard
    info = extract_standard(fname)
    return info['standard_code'] if info else None


def load_kb_codes():
    from kb_core.code_norm import extract_standard
    codes = {}
    if not os.path.isdir(KB_DIR): return codes
    for f in os.listdir(KB_DIR):
        if not f.endswith('.md'): continue
        si = extract_standard(f)
        if si and si['standard_code']:
            base, yr = si['standard_code'], si['year'] or 0
            codes[base] = max(yr, codes.get(base, 0))
    return codes


def phase_a(source_dir):
    """去重+预检+切割"""
    if not os.path.isdir(source_dir): return None, f'目录不存在: {source_dir}'
    session = Session()
    # 旧 session 未完成（非 done）→ 自动归档，避免 --resume 捡到旧 session 跳过新流程
    if session.data and session.data.get('phase_a', {}).get('status') != 'done':
        session.archive()
        session = Session()
    if session.data and session.data.get('phase_a', {}).get('status') == 'done':
        print('[Phase A] 已完成，跳过'); return session, None

    # G0: 文件名规范校验 (v6.22 — 阻断命名不规范的文件入库)
    validator = os.path.join(SCRIPTS_DIR, 'kb_validate_filenames.py')
    if os.path.exists(validator):
        vr = subprocess.run([sys.executable, validator, source_dir],
                           capture_output=True, text=True, timeout=60, cwd=SCRIPTS_DIR)
        print(vr.stdout)
        if vr.returncode != 0:
            return None, 'G0 文件名规范校验未通过，请修正后重新入库（详见上方输出）'

    print('[Phase A] 去重核验...')
    from kb_core.code_norm import extract_standard
    kb_codes = load_kb_codes()
    pdfs = [f for f in sorted(os.listdir(source_dir)) if f.endswith('.pdf')]
    info = {'total': len(pdfs), 'new': 0, 'duplicate': 0, 'updated': 0, 'invalid': 0, 'list': []}
    for pdf_name in pdfs:
        pp = os.path.join(source_dir, pdf_name)
        try:
            r = _read_pdf(pp)
            if r.is_encrypted or len(r.pages) == 0: info['invalid'] += 1; continue
        except: info['invalid'] += 1; continue
        si = extract_standard(pdf_name)
        if not si or not si['standard_code']: info['new'] += 1; info['list'].append(pdf_name); continue
        base, yr = si['standard_code'], si['year'] or 0
        if base in kb_codes:
            if yr > kb_codes[base]: info['updated'] += 1; info['list'].append(pdf_name)
            else: info['duplicate'] += 1
        else: info['new'] += 1; info['list'].append(pdf_name)

    total_new = info['new'] + info['updated']
    print(f'[Phase A] {info["total"]}扫描, {total_new}新增/更新, {info["duplicate"]}重复, {info["invalid"]}损坏')
    if total_new == 0: return None, None

    for f in info['list']:
        src = os.path.join(source_dir, f)
        if not os.path.exists(os.path.join(STAGING, f)): shutil.copy2(src, STAGING)
    subprocess.run([sys.executable, SPLITTER, '--dir', STAGING], capture_output=True, timeout=300, check=True)
    # 切割后删除已分块的原始大文件（分块已生成 _pXXXX-XXXX.pdf），避免 Phase B 误送原文件
    for f in os.listdir(STAGING):
        if f.endswith('.pdf') and not re.search(r'_p\d{4}-\d{4}\.pdf$', f):
            base = os.path.splitext(f)[0]
            has_chunks = any(c.startswith(base + '_p') for c in os.listdir(STAGING))
            if has_chunks:
                os.remove(os.path.join(STAGING, f))
                print(f'  [Phase A] 已切割, 删除原文件: {f}')

    session.create(source_dir, info)
    session.update_phase('a', status='done')
    return session, None


def phase_b(session):
    """MinerU提取"""
    if session.data.get('phase_b', {}).get('status') == 'done':
        print('[Phase B] 已完成'); return None
    print('[Phase B] MinerU提取...')
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, 'batch_extract.py'), '--all'],
                       capture_output=True, text=True, timeout=7200, cwd=SCRIPTS_DIR, check=False)
    if r.returncode != 0:
        print(r.stdout[-1000:] if len(r.stdout) > 1000 else r.stdout)
        return f'Phase B 失败 ({r.returncode}): 有分块提取未成功，检查 batch_failed.json 后可用 --retry-failed 重试'
    print(r.stdout[-1000:] if len(r.stdout) > 1000 else r.stdout)
    session.update_phase('b', status='done')
    return None


def count_vectors():
    meta_path = os.path.join(_cfg['paths']['vectordb'], 'metadata.json')
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else -1
    except (OSError, json.JSONDecodeError):
        return -1


def phase_c(session):
    """C1: MD导入+搜索索引 → [人工门自动退出] → C2: 条款索引+删源

    设计：C1完成后自动保存session并退出（不阻塞等人工门）。
    执行 --resume --phase c 继续C2。
    """
    cdata = session.data.setdefault('phase_c', {})

    if cdata.get('c1_attempted'):
        # C1 已执行过（无论成功/失败），直接跳到 C2
        print('[Phase C1] 已完成 → 跳过人工门，进入 C2')
    else:
        cdata['c1_attempted'] = True
        session._save()
        # 拍 md_manifest 快照（供 rollback 精确回滚，只删本次导入的文件）
        snap = os.path.join(SESSION_DIR, f'md_manifest_snapshot_{session.data["session_id"]}.json')
        if os.path.exists(MD_MANIFEST):
            shutil.copy2(MD_MANIFEST, snap)
            session.data['phase_c']['md_manifest_snapshot'] = snap
        else:
            session.data['phase_c']['md_manifest_snapshot'] = ''

        print('[Phase C1] MD导入...')
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, 'kb_import.py')],
                           capture_output=True, text=True, timeout=300, cwd=SCRIPTS_DIR)
        print(r.stdout[-1500:] if len(r.stdout) > 1500 else r.stdout)
        # 图片同步到永久库
        _img_src = os.path.join(_cfg['paths']['work_json'], 'images')
        _img_dst_rag = os.path.join(KB_DIR, 'images')
        _img_dst_perm = os.path.join(os.path.dirname(__file__), '..', 'data', 'images')
        if os.path.isdir(_img_src):
            for _dst in [_img_dst_rag, _img_dst_perm]:
                os.makedirs(_dst, exist_ok=True)
                _img_count = 0
                for _f in os.listdir(_img_src):
                    _src_fp = os.path.join(_img_src, _f)
                    _dst_fp = os.path.join(_dst, _f)
                    if not os.path.exists(_dst_fp):
                        shutil.copy2(_src_fp, _dst_fp)
                        _img_count += 1
                _label = 'kb_images'
                print(f'  图片同步: +{_img_count} → {_label}')
        subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, 'kb_search_index.py'), '--incremental'],
                       capture_output=True, timeout=300, cwd=SCRIPTS_DIR)
        # v6.16: 术语注入索引 — 扫描正文匹配已知术语
        term_index_script = os.path.join(SCRIPTS_DIR, 'kb_term_index.py')
        if os.path.exists(term_index_script):
            subprocess.run([sys.executable, term_index_script, '--incremental'],
                          capture_output=True, timeout=120, cwd=SCRIPTS_DIR)
        # v6.24: 短语模型 (含term_map白名单, PPR图依赖)
        phrase_script = os.path.join(SCRIPTS_DIR, 'kb_build_phrase_model.py')
        if os.path.exists(phrase_script):
            subprocess.run([sys.executable, phrase_script],
                          capture_output=True, timeout=120, cwd=SCRIPTS_DIR)
        # v6.23: BM25正文索引
        bm25_script = os.path.join(SCRIPTS_DIR, 'kb_body_bm25.py')
        if os.path.exists(bm25_script):
            subprocess.run([sys.executable, bm25_script],
                          capture_output=True, timeout=600, cwd=SCRIPTS_DIR)
        # v9.0: PPR 图重建 (F1 翻转: PPR 保留, 撤销 v6.24 下架; 解决17天旧图陈腐)。
        # 依赖 phrase_model + term_index + bm25 + search_index, 均已在上面重建; 仅全量。
        ppr_graph_script = os.path.join(SCRIPTS_DIR, 'kb_ppr_graph.py')
        if os.path.exists(ppr_graph_script):
            subprocess.run([sys.executable, ppr_graph_script],
                          capture_output=True, timeout=300, cwd=SCRIPTS_DIR)
        # v6.23: 条款编号索引 (精确查询直通车)
        clause_script = os.path.join(SCRIPTS_DIR, 'kb_clause_index.py')
        if os.path.exists(clause_script):
            subprocess.run([sys.executable, clause_script],
                          capture_output=True, timeout=60, cwd=SCRIPTS_DIR)
        # v6.23: 跨标准引用索引
        crossref_script = os.path.join(SCRIPTS_DIR, 'kb_cross_refs.py')
        if os.path.exists(crossref_script):
            subprocess.run([sys.executable, crossref_script],
                          capture_output=True, timeout=60, cwd=SCRIPTS_DIR)
        # v6.23: 图片元数据索引
        image_idx_script = os.path.join(SCRIPTS_DIR, 'kb_image_index.py')
        if os.path.exists(image_idx_script):
            subprocess.run([sys.executable, image_idx_script],
                          capture_output=True, timeout=60, cwd=SCRIPTS_DIR)
        cdata['md_imported'] = len([f for f in os.listdir(KB_DIR) if f.endswith('.md')])
        cdata['search_indexed'] = True
        cdata['vector_before'] = count_vectors()
        session._save()

        # 向量监听：等待嵌入完成
        # v9.0 修 B4: watcher 脚本缺失时优雅降级(原无守护→subprocess 必崩)。
        # 向量由外部 Obsidian 插件异步生成; 无 watcher 或无 Obsidian 环境(如 Codex)
        # 时跳过等待、继续 C2 —— 向量缺失不阻塞入库, 检索端对空向量库已能降级。
        watcher = os.path.join(SCRIPTS_DIR, 'kb_watch_vectors.py')
        if not os.path.exists(watcher):
            print('\n[向量监听] kb_watch_vectors.py 不存在 → 跳过向量等待(向量由外部'
                  ' Obsidian 插件异步生成; 无 Obsidian 环境可忽略), 继续 C2')
            cdata['vector_before'] = count_vectors()
        else:
            timeout = max(600, cdata['md_imported'] * 2)  # 至少10分钟，大库更长
            print('\n' + '='*50)
            print(f"[向量监听] 等待嵌入完成 (超时 {timeout}s)...")
            print("          可在 Obsidian 刷新知识库")
            print('='*50)
            wr = subprocess.run([sys.executable, watcher, '--timeout', str(timeout)],
                               timeout=timeout + 60, cwd=SCRIPTS_DIR, check=False)
            if wr.returncode == 0:
                # 嵌入+映射成功 → 自动继续 C2
                cdata['vector_before'] = cdata.get('vector_before', count_vectors())
            else:
                # 超时或用户未刷新 → 保存 session 退出，之后可 resume
                cdata['vector_before'] = count_vectors()
                session._save()
                print('\n[向量监听] 超时或中断，session 已保存')
                print('          之后执行: python pipeline_orchestrator.py --resume --phase c')
                return 'WAIT_HUMAN'

    if cdata.get('json_merged'): return None

    vector_now = count_vectors()
    print(f'[Phase C2] 向量: {session.data["phase_c"].get("vector_before",0)} → {vector_now}')

    # Snapshot + build_index
    manifest_path = os.path.join(KB_JSON_DIR, 'manifest.json')
    snap = os.path.join(SESSION_DIR, f'manifest_snapshot_{session.data["session_id"]}.json')
    if os.path.exists(manifest_path): shutil.copy2(manifest_path, snap)
    session.data['phase_c']['kb_json_snapshot'] = snap

    import getpass; user = getpass.getuser()
    build_script = _cfg['paths'].get('build_index_script', '')
    # Lift DENY → build_index → 备份永久库 → re-apply（finally 保证即使崩溃也恢复保护）
    subprocess.run(['icacls', KB_JSON_DIR, '/remove:d', user], capture_output=True)
    try:
        r = subprocess.run([sys.executable, build_script, '--incremental'],
                          capture_output=True, text=True, timeout=300, check=False)
        if r.returncode != 0:
            print(f'  WARNING: build_index failed (exit {r.returncode}): {r.stderr[-300:]}')
        else:
            pass  # build_index 成功
            # 浮动标签评分: 根据搜索日志更新文件标签
            scorer = os.path.join(SCRIPTS_DIR, 'tag_scorer.py')
            if os.path.exists(scorer):
                subprocess.run([sys.executable, scorer], capture_output=True, timeout=60)
    finally:
        subprocess.run(['cmd', '/c', f'icacls {KB_JSON_DIR} /deny {user}:(D,DC)'], capture_output=True)

    # Verify: 标准数不应比入库前少 (防止 build_index 破坏已有清单)
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            std_count = len(json.load(f).get('standards', {}))
        snap_count = 0
        if os.path.exists(snap):
            with open(snap, 'r', encoding='utf-8') as f:
                snap_count = len(json.load(f).get('standards', {}))
        if std_count < snap_count:
            if os.path.exists(snap): shutil.copy2(snap, manifest_path)
            return f'写入验证失败: 标准数从{snap_count}降到{std_count}，已恢复快照'
    # 清理 work_json 中间文件 (仅 _seg*.json，永久库不受影响):
    #   images/  — 永久图片库，不清理
    #   data/index/ 不清理
    #   kb_md/     — MD 永久库，不清理
    for f in os.listdir(WORK_JSON):
        if f.startswith('_seg') and f.endswith('.json'): os.remove(os.path.join(WORK_JSON, f))
    session.update_phase('c', json_merged=True, json_verified=True, vector_after=vector_now)
    return None


def phase_d(session):
    """验证+完整性校验+清理+归档"""
    # D1: 端到端抽查
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, 'kb_e2e_verify.py'), '--sample', '3'],
                       capture_output=True, text=True, timeout=120, cwd=SCRIPTS_DIR)
    e2e_ok = '[PASS]' in r.stdout if r.stdout else False
    print(r.stdout[-800:] if len(r.stdout) > 800 else r.stdout)

    # D2: 三库完整性校验
    verify_script = os.path.join(SCRIPTS_DIR, 'kb_verify_integrity.py')
    if os.path.exists(verify_script):
        r2 = subprocess.run([sys.executable, verify_script, '--alert'],
                           capture_output=True, text=True, timeout=60, cwd=SCRIPTS_DIR)
        integrity_ok = r2.returncode == 0
        print(r2.stdout[-500:] if len(r2.stdout) > 500 else r2.stdout)
    else:
        integrity_ok = False
        print('[WARN] kb_verify_integrity.py 不存在，跳过完整性校验')

    # 校验不通过 → 拒绝清理，保留 staging 供修复
    if not integrity_ok:
        session.update_phase('d', e2e_passed=e2e_ok, integrity='FAILED',
                            status='blocked')
        release_lock()
        return ('KB完整性校验未通过！已保留staging文件和会话，'
               '请检查三库一致性后再手动运行 phase_d')

    # D2.5: 搜索质量门 — 53用例评估 + 基线比对
    quality_script = os.path.join(SCRIPTS_DIR, 'kb_search_quality.py')
    if os.path.exists(quality_script):
        qr = subprocess.run([sys.executable, quality_script, '--check'],
                           capture_output=True, text=True, timeout=600, cwd=SCRIPTS_DIR)
        print(qr.stdout[-1000:] if len(qr.stdout) > 1000 else qr.stdout)
        if qr.returncode != 0:
            session.update_phase('d', e2e_passed=e2e_ok, integrity='PASSED',
                                search_quality='DEGRADED', status='blocked')
            release_lock()
            return ('搜索质量退化！已保留staging文件和会话，'
                    '请检查搜索变更并修复后重新运行 phase_d')
    else:
        print('[WARN] kb_search_quality.py 不存在，跳过搜索质量门')

    # D3: 清理临时文件 + 备份记忆层
    #   永久库不受影响: data/index/ data/md_lib_v2/ data/kb_json/ images/
    for f in os.listdir(STAGING):
        if f.endswith('.pdf'): os.remove(os.path.join(STAGING, f))
    for f in os.listdir(WORK_JSON):
        if f.startswith('_seg') and f.endswith('.md'): os.remove(os.path.join(WORK_JSON, f))


    # 清理快照文件（回滚已不再需要）
    for snap_key in ['md_manifest_snapshot', 'kb_json_snapshot']:
        snap_path = session.data.get('phase_c', {}).get(snap_key, '')
        if snap_path and os.path.exists(snap_path):
            try: os.remove(snap_path)
            except OSError: pass

    release_lock()
    session.update_phase('d', e2e_passed=e2e_ok, integrity='PASSED', status='done')
    session.archive()
    print(f'\nPipeline 闭环. 会话: {session.data["session_id"]}')
    return None


def main():
    import argparse
    p = argparse.ArgumentParser(description='Phase-Locked Pipeline Orchestrator')
    p.add_argument('source_dir', nargs='?')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--phase', choices=['a','b','c','d'])
    args = p.parse_args()

    ok, err = acquire_lock()
    if not ok: print(f'[LOCK] {err}'); sys.exit(1)

    try:
        if args.resume:
            session = Session()
            if not session.data: print('无session'); return
            print(f'恢复: {session.data["session_id"]}')
        elif args.phase:
            session = Session()
            if not session.data: print('无session'); return
        else:
            if not args.source_dir: print('请指定PDF目录'); return
            session, err = phase_a(args.source_dir)
            if err or session is None: print(f'Phase A: {err or "无新文件"}'); release_lock(); return

        run_all = not args.phase
        if (run_all or args.phase == 'b') and (err := phase_b(session)):
            print(f'Phase B 失败: {err}')
            if run_all: return  # B 失败则停止，可用 --retry-failed + --resume 重试
        if (run_all or args.phase == 'c'):
            err = phase_c(session)
            if err == 'WAIT_HUMAN':
                print('[Pipeline] C1完成')
                return  # 优雅退出，等待用户操作（锁在 finally 释放）
            elif err: print(f'Phase C fail: {err}')
        if (run_all or args.phase == 'd') and (err := phase_d(session)): print(f'Phase D fail: {err}')
    finally:
        # 无论成功/失败/崩溃，始终释放锁
        release_lock()

if __name__ == '__main__': main()
