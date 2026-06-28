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
