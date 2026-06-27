"""自动变更日志 — 嵌入脚本入口，调用即记录。不可绕过。"""
import os, json, time

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.changelog.jsonl')

def record(caller_file=None, args=None):
    """每次脚本启动时调用。记录时间/文件/参数。"""
    entry = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'caller': os.path.basename(caller_file or 'unknown'),
        'args': ' '.join(args[:20]) if args else '',
    }
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        pass  # 磁盘满/权限问题 → 安静失败，不影响主流程

def log_file_change(filepath, action='modified'):
    """记录文件变更（供 mtime 扫描器调用）"""
    entry = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'type': 'file_change',
        'path': filepath,
        'action': action,
    }
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        pass

def log_kb_status(standards, clauses, md_files):
    """记录 KB 全景快照"""
    entry = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'type': 'kb_status',
        'standards': standards,
        'clauses': clauses,
        'md_files': md_files,
    }
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        pass

def read_log(limit=20):
    """读取最近 N 条日志"""
    if not os.path.exists(LOG_PATH):
        return []
    lines = []
    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(json.loads(line))
    return lines[-limit:]
