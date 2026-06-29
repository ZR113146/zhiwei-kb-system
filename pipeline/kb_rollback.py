"""知识库回滚 — 按会话撤销，含 kb_json manifest 快照恢复
v2: 修复 P0-3(会话目录) P0-4(数据结构) P0-5(DENY阻塞)
用法: python kb_rollback.py --list | --last | --session <id>
"""
import os, json, sys, shutil, subprocess
from datetime import datetime
# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
from kb_core.kb import load_config
import kb_core.changelog as changelog; changelog.record(__file__, sys.argv)

_cfg = load_config()
KB_DIR = _cfg['paths']['kb_md']
KB_MD_LIB = _cfg['paths'].get('kb_md_lib', os.path.join(os.path.dirname(__file__), '..', 'data', 'md_lib_v2'))
MD_MANIFEST = _cfg['paths']['md_manifest']
KB_JSON_DIR = _cfg['paths']['kb_json']
SESSION_DIR = os.path.join(os.path.dirname(MD_MANIFEST), 'sessions')  # 修复: 会话在 sessions/ 子目录

def list_sessions():
    sessions = []
    if not os.path.exists(SESSION_DIR):
        print(f'会话目录不存在: {SESSION_DIR}')
        return []
    for f in os.listdir(SESSION_DIR):
        # 跳过子目录（completed/, rollback_archive/）
        fp = os.path.join(SESSION_DIR, f)
        if not os.path.isfile(fp):
            continue
        if f.startswith('session_') and f.endswith('.json'):
            try:
                d = json.load(open(fp, 'r', encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                continue
            fcount = d.get('files', {}).get('total', '?')
            sessions.append((
                f.replace('session_', '').replace('.json', ''),
                d.get('session_id', '?'),
                fcount
            ))
    if not sessions:
        print('无会话')
        return []
    print(f'{"会话ID":<20} {"文件":<8}')
    print('-' * 30)
    for s in sorted(sessions, reverse=True):
        print(f'{s[0]:<20} {s[2]:<8}')
    return sessions


def rollback(session_id):
    """回滚指定 session 的入库操作。

    方法：比对 md_manifest 入库前快照与当前状态，
    只删除本次 session 新增的 MD 文件，然后恢复快照。
    """
    sp = os.path.join(SESSION_DIR, f'session_{session_id}.json')
    if not os.path.exists(sp):
        print(f'会话不存在: {session_id}')
        return False

    session = json.load(open(sp, 'r', encoding='utf-8'))
    cdata = session.get('phase_c', {})

    # ── 1. 比对 md_manifest 快照，只删本次导入的文件 ──
    md_snap_path = cdata.get('md_manifest_snapshot', '')
    removed = 0

    if md_snap_path and os.path.exists(md_snap_path):
        snap = json.load(open(md_snap_path, 'r', encoding='utf-8'))
        snap_imported = set(snap.get('imported', {}).keys())

        if os.path.exists(MD_MANIFEST):
            current = json.load(open(MD_MANIFEST, 'r', encoding='utf-8'))
        else:
            current = {"_meta": {}, "imported": {}}
        current_imported = current.get('imported', {})

        # 找出本次新增的条目（当前有、快照没有）
        new_keys = set(current_imported.keys()) - snap_imported

        for key in new_keys:
            info = current_imported[key]
            # info 是 {"title": ..., "kb_path": "...", "imported_at": "..."}
            if isinstance(info, dict):
                kb_path = info.get('kb_path', '')
                if kb_path and os.path.exists(kb_path):
                    try:
                        os.remove(kb_path)
                        removed += 1
                        print(f'  已删除: {os.path.basename(kb_path)}')
                    except OSError as e:
                        print(f'  删除失败: {os.path.basename(kb_path)}: {e}')
                # 同时删除 kb_md 库中的同名文件
                md_name = os.path.basename(kb_path) if kb_path else ''
                if md_name:
                    lib_path = os.path.join(KB_MD_LIB, md_name)
                    if os.path.exists(lib_path):
                        try:
                            os.remove(lib_path)
                            print(f'  已删除(lib): {md_name}')
                        except OSError:
                            pass

        # 恢复快照（覆盖当前 manifest）
        manifest = snap
        manifest['_meta']['updated'] = datetime.now().isoformat()
        with open(MD_MANIFEST, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 清理快照文件
        try:
            os.remove(md_snap_path)
        except OSError:
            pass

        print(f'  快照比对: {len(new_keys)} 条新增, {removed} 个MD文件删除')
    else:
        # 兼容旧 session（没有 md_manifest 快照）：跳过 MD 清理
        print('  (无 md_manifest 快照，跳过 MD 文件清理)')

    # ── 2. 恢复 kb_json manifest 快照 ──
    json_snap = cdata.get('kb_json_snapshot', '')
    recovered = False
    if json_snap and os.path.exists(json_snap):
        mt = os.path.join(KB_JSON_DIR, 'manifest.json')
        try:
            import getpass; user = getpass.getuser()
            subprocess.run(['icacls', KB_JSON_DIR, '/remove:d', user],
                         capture_output=True, timeout=10)
            if os.path.exists(mt):
                os.remove(mt)
            shutil.copy2(json_snap, mt)
            os.remove(json_snap)
            recovered = True
            subprocess.run(['icacls', KB_JSON_DIR, '/deny', f'{user}:(D,DC)'],
                         capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f'  kb_json 快照恢复失败: {e}')

    # ── 3. 归档会话 ──
    arch = os.path.join(SESSION_DIR, 'completed')
    os.makedirs(arch, exist_ok=True)
    try:
        shutil.move(sp, os.path.join(arch, f'session_{session_id}.json'))
    except shutil.Error:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.move(sp, os.path.join(arch, f'session_{session_id}_{ts}.json'))

    print(f'回滚完成: {removed}个MD文件删除, '
          f'{"kb_json已恢复" if recovered else "无快照"}, '
          f'会话已归档')


def main():
    import argparse
    p = argparse.ArgumentParser(description='知识库回滚')
    p.add_argument('--list', action='store_true')
    p.add_argument('--session')
    p.add_argument('--last', action='store_true')
    args = p.parse_args()

    if args.list:
        list_sessions()
    elif args.last:
        ss = list_sessions()
        if ss:
            rollback(ss[0][0])
    elif args.session:
        rollback(args.session)
    else:
        p.print_help()


if __name__ == '__main__':
    main()
