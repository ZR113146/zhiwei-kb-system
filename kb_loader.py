'''Codex 平台知识库接入层

提供简化的 4 个 API 给 Codex Skill 使用：
  search(query)        — 混合搜索
  read_clause(code, n) — 读取条款原文
  status()             — 库统计
  search_vector(q)     — 纯向量搜索
'''

import sys, os

_ROOT = os.path.dirname(os.path.abspath(__file__))
_kb_core = os.path.join(_ROOT, 'kb_core')
_pipeline = os.path.join(_ROOT, 'pipeline')

for p in [_kb_core, _pipeline, _ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from kb_core.kb_resolver_core import KBResolver
import json

_CFG_PATH = os.path.join(_ROOT, 'kb_core', 'kb.json')
with open(_CFG_PATH, 'r', encoding='utf-8') as _f:
    _CFG = json.load(_f)
_VECTOR_WEIGHT = _CFG.get('search', {}).get('default_vector_weight', 0.3)
from kb_vector_search_local import LocalSemanticSearch

_kb = KBResolver()
_vs = LocalSemanticSearch()


def search(query: str, max_results: int = 5) -> list:
    '''混合搜索（关键词+PPR图+向量语义）'''
    return _kb.search(query, max_results=max_results, vector_weight=_VECTOR_WEIGHT)


def search_with_support(query: str, max_results: int = 5, mode: str = 'annotate') -> list:
    '''混合搜索，并附加真实性支撑诊断；默认只标注，不改变排序。'''
    from kb_core.support_guard import annotate_results
    results = _kb.search(query, max_results=max_results, vector_weight=_VECTOR_WEIGHT)
    guard_cfg = _CFG.get('search', {}).get('support_guard', {})
    truth_path = guard_cfg.get('truth_path', 'eval/truth_queries_seed.jsonl')
    if not os.path.isabs(truth_path):
        truth_path = os.path.join(_ROOT, truth_path)
    top_k = int(guard_cfg.get('top_k', max_results) or max_results)
    return annotate_results(query, results, truth_path, mode=mode, top_k=top_k)


def read_clause(code: str, clause: str = '') -> str:
    '''读取指定规范的条款原文'''
    return _kb.read_clause(code, clause) or ''


def read_clause_full(code: str, clause: str = '', prefer_type: str = None) -> dict:
    '''读取结构化条文对象，用于引用审计和方案生成。'''
    return _kb.read_clause_full(code, clause, prefer_type)


def status() -> dict:
    '''知识库统计信息'''
    return _kb.stats()


def search_vector(query: str, top_k: int = 5) -> list:
    '''纯向量语义搜索'''
    return _vs.search(query, top_k=top_k)


def feedback(entry: dict) -> dict:
    '''记录检索/引用反馈，供后续评测与优化使用。'''
    return _kb.feedback(entry)
