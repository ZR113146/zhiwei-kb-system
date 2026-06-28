"""Process kb_feedback.jsonl to generate improvement suggestions (v6.18).

Run periodically (manual or cron) to analyze consumer feedback and generate
actionable suggestions for term map expansion, tag optimization, and search tuning.

Output: prints analysis report. Writes kb_feedback_suggestions.json.
"""
import os, re, json, sys
from collections import Counter, defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_LOG = os.path.join(SCRIPT_DIR, 'kb_feedback.jsonl')
TERM_MAP = os.path.join(SCRIPT_DIR, '..', 'contracts', 'term_map.json')
SUGGESTIONS = os.path.join(SCRIPT_DIR, 'kb_feedback_suggestions.json')


def load_feedback():
    entries = []
    if not os.path.exists(FEEDBACK_LOG):
        return entries
    with open(FEEDBACK_LOG, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def analyze(entries):
    if not entries:
        return {'status': 'no_data', 'message': 'No feedback entries yet'}

    zero_queries = Counter()
    cited_codes = Counter()
    cited_clauses = Counter()
    ai_fallback_queries = []
    used_terms = Counter()
    rank_dist = Counter()

    for e in entries:
        t = e.get('type', '')
        q = e.get('query', '')

        if t == 'zero_result':
            zero_queries[q] += 1

        if e.get('clause_cited'):
            cited_clauses[f"{e.get('result_used', {}).get('code', '?')} {e.get('clause_cited', '')}"] += 1

        if e.get('result_used', {}).get('code'):
            cited_codes[e['result_used']['code']] += 1

        if e.get('ai_fallback'):
            ai_fallback_queries.append(q)

        if e.get('result_used', {}).get('rank'):
            rank_dist[e['result_used']['rank']] += 1

        for tterm in e.get('terms_matched', []):
            used_terms[tterm] += 1

    # Suggestions
    suggestions = []

    # 1. Zero-result queries → potential new term map entries
    if zero_queries:
        top_zeros = zero_queries.most_common(10)
        suggestions.append({
            'type': 'zero_result_terms',
            'title': '高频零结果查询 (建议扩充术语映射表)',
            'queries': [{'query': q, 'count': c} for q, c in top_zeros]
        })

    # 2. AI fallback → search quality gaps
    if ai_fallback_queries:
        fb_terms = Counter(ai_fallback_queries)
        suggestions.append({
            'type': 'ai_fallback_gap',
            'title': 'AI 需自行补充判断的查询 (搜索质量不足)',
            'queries': [{'query': q, 'count': c} for q, c in fb_terms.most_common(10)]
        })

    # 3. Low-rank usage → ranking needs tuning
    low_rank = sum(c for r, c in rank_dist.items() if r > 3)
    high_rank = sum(c for r, c in rank_dist.items() if r <= 3)
    if low_rank > 0:
        suggestions.append({
            'type': 'rank_quality',
            'title': f'排序质量: {high_rank}次使用top-3结果, {low_rank}次使用rank>3结果',
            'rank_distribution': dict(rank_dist)
        })

    # 4. Top cited → hot clauses
    if cited_clauses:
        suggestions.append({
            'type': 'hot_clauses',
            'title': '高频引用条款 (可进入热门索引)',
            'clauses': [{'clause': k, 'count': v} for k, v in cited_clauses.most_common(20)]
        })

    # 5. Top cited codes → tag priority
    if cited_codes:
        suggestions.append({
            'type': 'hot_codes',
            'title': '高频引用规范 (可提升标签优先级)',
            'codes': [{'code': k, 'count': v} for k, v in cited_codes.most_common(20)]
        })

    return {
        'status': 'ok',
        'total_entries': len(entries),
        'zero_result_count': sum(zero_queries.values()),
        'ai_fallback_count': len(ai_fallback_queries),
        'unique_queries': len(set(e.get('query', '') for e in entries)),
        'suggestions': suggestions
    }


def main():
    entries = load_feedback()
    report = analyze(entries)

    print(f"Feedback Analysis ({len(entries)} entries)")
    print(f"  Zero results: {report.get('zero_result_count', 0)}")
    print(f"  AI fallbacks: {report.get('ai_fallback_count', 0)}")
    print(f"  Unique queries: {report.get('unique_queries', 0)}")
    print()

    for s in report.get('suggestions', []):
        print(f"[{s['type']}] {s['title']}")
        if 'queries' in s:
            for q in s['queries'][:5]:
                print(f"  {q['count']}x '{q['query']}'")
        if 'clauses' in s:
            for c in s['clauses'][:5]:
                print(f"  {c['count']}x {c['clause']}")
        print()

    # Write suggestions file
    with open(SUGGESTIONS, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Suggestions written to {SUGGESTIONS}")


if __name__ == '__main__':
    main()
