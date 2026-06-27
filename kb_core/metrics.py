"""可观测性 — 搜索延迟追踪 + KB状态快照历史
自动记录，零手动操作。被 kb.py 的 search/status 方法内部调用。
"""
import os, json, time

METRICS_DIR = os.path.dirname(os.path.abspath(__file__))
SEARCH_LOG = os.path.join(METRICS_DIR, '.metrics_search.jsonl')
STATUS_LOG = os.path.join(METRICS_DIR, '.metrics_status.jsonl')
MAX_ENTRIES = 1000  # 每种日志最多保留 1000 条

def record_search(query, duration_ms, result_count, mode='hybrid'):
    """每次 search() 调用后自动记录"""
    entry = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'query': query[:80],
        'duration_ms': round(duration_ms, 1),
        'results': result_count,
        'mode': mode,
    }
    _append(SEARCH_LOG, entry)

def record_status(standards, clauses, md_files, vectors=None):
    """每次 status() 调用后自动记录 KB 快照"""
    # 只在数值变化时记录（去重）
    last = _read_last(STATUS_LOG)
    if last and last.get('standards') == standards and last.get('clauses') == clauses:
        return
    entry = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'standards': standards,
        'clauses': clauses,
        'md_files': md_files,
        'vectors': vectors,
    }
    _append(STATUS_LOG, entry)

def search_stats(last_n=20):
    """读取最近 N 次搜索的性能统计"""
    entries = _read_last_n(SEARCH_LOG, last_n)
    if not entries:
        return {'count': 0, 'avg_ms': 0, 'p50_ms': 0, 'p95_ms': 0, 'max_ms': 0}
    durations = sorted([e['duration_ms'] for e in entries])
    n = len(durations)
    return {
        'count': n,
        'avg_ms': round(sum(durations) / n, 1),
        'p50_ms': durations[n // 2],
        'p95_ms': durations[int(n * 0.95)],
        'max_ms': durations[-1],
    }

def status_history(last_n=10):
    """KB 规模变化历史"""
    return _read_last_n(STATUS_LOG, last_n)

def _append(log_path, entry):
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        pass

def _read_last_n(log_path, n):
    if not os.path.exists(log_path):
        return []
    lines = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(json.loads(line))
    return lines[-n:]

def _read_last(log_path):
    entries = _read_last_n(log_path, 1)
    return entries[0] if entries else {}
