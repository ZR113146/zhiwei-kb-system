#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared retrieval facade for Zhiwei plan workflows.

This module is intentionally thin: it centralizes scenario-specific entrypoints
without changing existing KB ranking weights or resolver behavior. Callers can
migrate to it gradually while keeping current quality baselines stable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

CLAUSE_NO_RE = re.compile(r'(?<![\d.])(\d+(?:\.\d+)+)(?![\d.])')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kb_core'))
from kb_core.kb import KB  # noqa: E402


TOPIC_KEYWORDS = {
    'earthwork': '土方 开挖 回填 压实 分层',
    'concrete': '混凝土 浇筑 振捣 养护 拆模',
    'masonry': '砌筑 灰缝 砂浆 砖',
    'paving': '铺装 面层 结合层 养护',
    'planting': '栽植 苗木 种植 土球',
    'pipeline': '管道 安装 试验 水压',
    'steel': '钢结构 安装 焊接 涂装',
    'demolition': '拆除 破碎 清理',
    'quality_system': '质量 验收 检验批',
    'acceptance': '验收 允许偏差 检验',
    'defect_prevention': '通病 防治 空鼓 裂缝',
    'safety_system': '安全 责任制 检查',
    'process_safety': '高处 机械 用电 消防',
    'emergency': '应急 救援 预案',
    'electrical': '用电 配电 保护',
    'metro_protection': '地铁 监测 沉降 保护',
    'noise': '噪声 排放 分贝',
    'fire': '消防 灭火 器材',
}


@dataclass
class RetrievalRequest:
    mode: str
    query: str = ''
    constraints: Dict[str, Any] = field(default_factory=dict)
    limits: Dict[str, Any] = field(default_factory=dict)


class RetrievalCore:
    def __init__(self, kb: Optional[KB] = None):
        self.kb = kb or KB()

    def match(self, request: RetrievalRequest | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(request, dict):
            request = RetrievalRequest(**request)
        start = time.time()
        mode = request.mode
        if mode == 'general_search':
            results = self.search_general(request.query, request.constraints, request.limits)
        elif mode == 'chapter_recommend':
            results = self.recommend_chapter(request.constraints, request.limits)
        elif mode == 'citation_discovery':
            results = self.discover_citations(request.query, request.constraints, request.limits)
        elif mode == 'long_context_search':
            results = self.search_long_context(request.query, request.constraints, request.limits)
        else:
            raise ValueError(f'unsupported retrieval mode: {mode}')
        return {
            'mode': mode,
            'query': request.query,
            'results': results,
            'trace': {
                'elapsed_ms': int((time.time() - start) * 1000),
                'used_llm': False,
            },
        }

    def search_general(self, query: str, constraints: Dict[str, Any], limits: Dict[str, Any]) -> List[Dict[str, Any]]:
        max_results = int(limits.get('max_results', 5))
        vector_weight = limits.get('vector_weight')
        support_guard = bool(limits.get('support_guard', False))
        support_guard_mode = limits.get('support_guard_mode')
        support_truth_path = limits.get('support_truth_path')
        raw = self.kb.search(
            query,
            max_results=max_results,
            vector_weight=vector_weight,
            project_standards=constraints.get('project_standards'),
            must=constraints.get('must'),
            must_not=constraints.get('must_not'),
            prefer=constraints.get('prefer'),
            support_guard=support_guard,
            support_guard_mode=support_guard_mode,
            support_truth_path=support_truth_path,
        )
        return [self._normalize_search_result(item, 'kb_search') for item in raw]

    def search_long_context(self, text: str, constraints: Dict[str, Any], limits: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = self._keywords_from_text(text, max_words=int(limits.get('max_words', 6)))
        if not query:
            return []
        guarded_limits = dict(limits)
        guarded_limits.setdefault('support_guard', True)
        return self.search_general(query, constraints, guarded_limits)

    def recommend_chapter(self, constraints: Dict[str, Any], limits: Dict[str, Any]) -> List[Dict[str, Any]]:
        codes = constraints.get('codes') or []
        topic = constraints.get('topic', '')
        max_clauses = int(limits.get('max_clauses', 3))
        topic_query = TOPIC_KEYWORDS.get(topic, topic)
        results = []
        for code in codes:
            name, _, _ = self.kb.get_name(code)
            clauses = self._local_headings(code, topic_query, max_clauses)
            citations = [c['citation'] for c in clauses if c.get('citation')]
            results.append({
                'code': code,
                'name': name,
                'clause': '',
                'text': '',
                'score': 1.0 if clauses else 0.5,
                'confidence': 'high' if clauses else 'mid',
                'source': 'local_md',
                'reason': f'chapter topic={topic}',
                'clauses': clauses,
                'citations': citations,
            })
        return results

    def discover_citations(self, paragraph: str, constraints: Dict[str, Any], limits: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self._looks_citable(paragraph):
            return []
        guarded_limits = dict(limits)
        guarded_limits.setdefault('support_guard', True)
        return self.search_long_context(paragraph, constraints, guarded_limits)

    def _local_headings(self, code: str, topic_query: str, max_clauses: int) -> List[Dict[str, Any]]:
        md = self.kb.read_md(code) or ''
        headings = []
        terms = [t for t in re.split(r'\s+', topic_query) if t]
        for line in md.splitlines():
            match = re.match(r'^#{1,6}\s+(.+?)\s*$', line)
            if not match:
                continue
            heading = match.group(1).strip()
            if terms and not any(term in heading for term in terms):
                continue
            headings.append(self._clause_candidate(code, heading))
            if len(headings) >= max_clauses:
                break
        if headings:
            return headings
        for line in md.splitlines():
            match = re.match(r'^#{1,6}\s+(.+?)\s*$', line)
            if match:
                headings.append(self._clause_candidate(code, match.group(1).strip()))
            if len(headings) >= max_clauses:
                break
        return headings

    def _clause_candidate(self, code: str, heading: str) -> Dict[str, Any]:
        item = {'heading': heading, 'snippet': ''}
        match = CLAUSE_NO_RE.search(heading)
        if not match:
            return item
        data = self.kb.read_clause_full(code, match.group(1))
        if not data or data.get('error'):
            return item
        citation = data.get('citation') or {}
        if citation:
            item['citation'] = citation
            item['clause_no'] = citation.get('clause_no', match.group(1))
            item['clause_type'] = citation.get('clause_type', data.get('clause_type', 'unknown'))
            item['audit_status'] = citation.get('audit_status', 'unknown')
        return item

    def _normalize_search_result(self, item: Dict[str, Any], source: str) -> Dict[str, Any]:
        return {
            'code': item.get('code', ''),
            'name': item.get('name', ''),
            'clause': item.get('heading', ''),
            'text': item.get('text', ''),
            'score': item.get('score', item.get('hits', 0)),
            'confidence': item.get('confidence', 'mid'),
            'source': item.get('_source', source),
            'support_action': item.get('support_action', ''),
            'support_judgment': item.get('support_judgment', ''),
            'support_signals': item.get('support_signals', {}),
            'support_guard': item.get('support_guard', {}),
            'reason': item.get('heading', ''),
            'raw': item,
        }

    def _keywords_from_text(self, text: str, max_words: int = 6) -> str:
        words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        stop = {'施工前', '施工中', '施工后', '完成后', '检查时', '验收前', '过程中',
                '应当', '必须', '可以', '需要', '进行', '采用', '用于', '以及',
                '因此', '所以', '同时', '此外', '另外', '并且', '或者', '本工程'}
        picked = [word for word in words if not any(s in word for s in stop)]
        return ' '.join(picked[:max_words])

    def _looks_citable(self, text: str) -> bool:
        if len(text.strip()) < 20:
            return False
        has_number = re.search(r'\d+\.?\d*\s*(?:mm|cm|m|kN|kPa|MPa|℃|%|d|天|kg|㎡)', text)
        has_code = re.search(r'(?:GB|JGJ|CJJ|CECS|DB|TCECS)\s*/?\s*T?\s*\d+', text)
        return bool(has_number and not has_code)


def match(request: RetrievalRequest | Dict[str, Any], kb: Optional[KB] = None) -> Dict[str, Any]:
    return RetrievalCore(kb).match(request)


def _self_test() -> int:
    core = RetrievalCore()
    checks = []
    truth_path = os.path.join(os.path.dirname(__file__), '..', 'eval', 'truth_queries_seed.jsonl')
    truth_query = ''
    try:
        with open(truth_path, 'r', encoding='utf-8') as f:
            truth_query = json.loads(f.readline()).get('query', '')
    except Exception:
        truth_query = ''
    general = core.match({'mode': 'general_search', 'query': '混凝土 养护', 'limits': {'max_results': 3}})
    checks.append(('general_search', len(general['results']) > 0))
    guarded = core.match({
        'mode': 'general_search',
        'query': truth_query,
        'limits': {'max_results': 3, 'support_guard': True},
    })
    checks.append(('support_guard_annotation', bool(truth_query) and any(item.get('support_action') for item in guarded['results'])))
    chapter = core.match({
        'mode': 'chapter_recommend',
        'constraints': {'topic': 'paving', 'codes': ['GB50209', 'CJJ82']},
        'limits': {'max_clauses': 2},
    })
    checks.append(('chapter_recommend', len(chapter['results']) == 2))
    discovery = core.match({
        'mode': 'citation_discovery',
        'query': '铺装面层平整度允许偏差不应大于10mm，施工后应检查。',
        'limits': {'max_results': 3},
    })
    checks.append(('citation_discovery', len(discovery['results']) > 0))
    for name, ok in checks:
        print(f'[{"PASS" if ok else "FAIL"}] {name}')
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Zhiwei shared retrieval facade')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--mode', default='general_search')
    parser.add_argument('--query', default='')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(_self_test())
    result = match({'mode': args.mode, 'query': args.query})
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result['results']:
            print(f"{item.get('score', '')}\t{item.get('clause', '')}\t{item.get('text', '')[:80]}")
