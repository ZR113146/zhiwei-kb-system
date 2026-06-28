# -*- coding: utf-8 -*-
"""KBResolver 行为快照回归测试 (重构安全网)。

目的: 在重构 KBResolver / kb_core 前固化检索主干的"行为契约", 重构前后对比,
任何召回退化都会被捕获。

分支感知设计 (见 memory: zhiwei-kb-search-nondeterminism):
  - deterministic 分支 (direct/filename_title/legacy/empty): 跨进程 100% 可复现,
    做严格逐条身份比对 (file/source/heading/standard_code/confidence 精确, score 容差)。
  - ppr+legacy 分支 (NL 查询): 因并行线程完成顺序 + PPR 时序跨进程不确定, 逐条身份
    断言会误报; 改用**聚合召回指纹** (recall@5/mrr/ndcg, 实测跨进程完全一致) 守护质量。

其它设计要点:
  - 仅用标准库, 不依赖 pytest, 与项目现有 `python -m`/脚本风格一致。
  - 强制离线确定性: 运行前清除 ANTHROPIC_API_KEY, 使 _llm_rerank 成为 no-op。
  - score 四舍五入吸收浮点噪声; 不记录 _trace / 耗时等易变字段。

用法:
  生成基线:   python eval/snapshot_regression.py --update
  回归对比:   python eval/snapshot_regression.py
  指定基线:   python eval/snapshot_regression.py --baseline eval/snapshot_baseline.json
退出码: 0 = 一致 / 基线已写; 1 = 检测到漂移; 2 = 运行错误。
"""

import argparse
import json
import os
import sys

# 强制离线确定性: 必须在导入检索栈之前清除, 让 DeepSeek listwise 重排成为 no-op。
os.environ.pop("ANTHROPIC_API_KEY", None)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in ("", "kb_core", "pipeline"):
    path = os.path.join(ROOT, rel) if rel else ROOT
    if path not in sys.path:
        sys.path.insert(0, path)

import kb_loader as kl  # noqa: E402

DEFAULT_BASELINE = os.path.join(ROOT, "eval", "snapshot_baseline.json")
GOLDEN_QUERIES = os.path.join(ROOT, "eval", "golden_queries.jsonl")
TRUTH_QUERIES = os.path.join(ROOT, "eval", "truth_queries_seed.jsonl")
CLAUSE_SAMPLES = os.path.join(ROOT, "eval", "clause_golden_samples.json")

# search() 结果中纳入快照的稳定身份字段; 易变字段 (_trace/hits/耗时) 一律排除。
MAX_RESULTS = 5
SCORE_NDIGITS = 2
CLAUSE_FP_LEN = 400  # read_clause 文本指纹截断长度

# 分支感知比对 (见 memory: zhiwei-kb-search-nondeterminism)。
# 跨进程实测:
#   - direct / filename_title / legacy / empty 分支 100% 确定 -> 严格逐条比对
#     (file/source/heading/standard_code/confidence 精确, score 容差)。
#   - ppr+legacy 分支 (NL 查询) 因 ThreadPoolExecutor 完成顺序 + kb_ppr_engine.discover
#     时序, 跨进程会落入不同"吸引子", 个例 top-5 Jaccard 可低至 0.11; 零代码改动也如此。
#     故对该分支**不做逐条身份断言**, 仅记录供人工查看, 用聚合召回指纹守护质量
#     (recall@5/mrr/ndcg 实测跨进程完全一致, 因其度量"正确标准是否仍被召回")。
SCORE_TOLERANCE = 1.0
DETERMINISTIC_BRANCHES = {"direct", "filename_title", "legacy", "empty", ""}
# 聚合指标容差: 实测跨进程 delta=0, 留极小余量吸收未来浮点变动。
AGG_TOLERANCE = 0.01


def _load_jsonl(path):
    items = []
    if not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _collect_queries():
    """汇总去重查询集, 保持稳定顺序 (golden -> truth -> verify_chain)。
    保留 golden 项的 expected_* 元数据用于聚合召回指纹。"""
    seen = set()
    queries = []

    def add(q, source, item=None):
        q = (q or "").strip()
        if q and q not in seen:
            seen.add(q)
            queries.append({
                "query": q,
                "source": source,
                "query_type": (item or {}).get("query_type", ""),
                "expected_standard_code": (item or {}).get("expected_standard_code", ""),
                "expected_standard_name": (item or {}).get("expected_standard_name", ""),
            })

    for item in _load_jsonl(GOLDEN_QUERIES):
        add(item.get("query", ""), "golden", item)
    for item in _load_jsonl(TRUTH_QUERIES):
        add(item.get("query", ""), "truth", item)
    # __verify_chain 里历史关注的核心 NL 查询
    for q in ("地面铺装平整度", "保护层厚度", "GB50204 模板", "钢筋接头位置"):
        add(q, "verify_chain")
    return queries


def _result_signature(result):
    """提取单条结果的稳定身份指纹。"""
    return {
        "file": result.get("file", ""),
        "source": result.get("_source", ""),
        "heading": (result.get("heading", "") or "")[:120],
        "score": round(float(result.get("score", 0) or 0), SCORE_NDIGITS),
        "standard_code": result.get("standard_code", ""),
        "confidence": result.get("confidence", ""),
    }


def _snapshot_search():
    """对每条查询跑 search, 记录身份指纹 + 分支 + 召回命中 (用于聚合指纹)。"""
    # 复用 kb_eval 的 ground-truth 匹配逻辑, 与现有评测口径一致。
    from kb_eval import result_matches  # noqa: E402

    rows = []
    for entry in _collect_queries():
        query = entry["query"]
        expected_code = entry.get("expected_standard_code", "")
        expected_name = entry.get("expected_standard_name", "")
        try:
            results = kl.search(query, max_results=MAX_RESULTS)
            sigs = [_result_signature(r) for r in results]
            branch = (results[0].get("_trace", {}) or {}).get("branch", "") if results else "empty"
            first_rank = None
            for idx, r in enumerate(results, 1):
                if first_rank is None and result_matches(r, expected_code, expected_name):
                    first_rank = idx
                    break
            error = ""
        except Exception as exc:  # noqa: BLE001 - 快照需记录错误本身
            sigs = []
            branch = "error"
            first_rank = None
            error = f"{type(exc).__name__}: {exc}"
        rows.append({
            "query": query,
            "source": entry["source"],
            "query_type": entry.get("query_type", ""),
            "branch": branch,
            "result_count": len(sigs),
            "first_rank": first_rank,            # 召回命中名次 (None=未命中)
            "has_expected": bool(expected_code or expected_name),
            "results": sigs,
            "error": error,
        })
    return rows


def _aggregate_fingerprint(search_rows):
    """对有 ground-truth 的查询计算聚合召回指纹。
    这些指标跨进程稳定 (度量"正确标准是否被召回"), 是 ppr+legacy 分支的守护。"""
    import math

    scored = [r for r in search_rows if r.get("has_expected")]
    n = len(scored)
    if not n:
        return {"count": 0}

    def recall(rows):
        return round(sum(1 for r in rows if r.get("first_rank")) / len(rows), 4) if rows else None

    def mrr(rows):
        return round(sum(1.0 / r["first_rank"] for r in rows if r.get("first_rank")) / len(rows), 4) if rows else None

    def ndcg(rows):
        return round(sum(1.0 / math.log2(r["first_rank"] + 1) for r in rows if r.get("first_rank")) / len(rows), 4) if rows else None

    fp = {
        "count": n,
        "recall_at_5": recall(scored),
        "mrr": mrr(scored),
        "ndcg": ndcg(scored),
        "no_result_rate": round(sum(1 for r in scored if r["result_count"] == 0) / n, 4),
        "errors": sum(1 for r in scored if r["error"]),
    }
    # 仅对易变的 ppr+legacy 分支单列, 这是该分支唯一被断言的守护。
    ppr_rows = [r for r in scored if r.get("branch") not in DETERMINISTIC_BRANCHES]
    fp["ppr_branch"] = {
        "count": len(ppr_rows),
        "recall_at_5": recall(ppr_rows),
        "mrr": mrr(ppr_rows),
        "ndcg": ndcg(ppr_rows),
    }
    return fp


def _snapshot_clauses():
    rows = []
    if not os.path.exists(CLAUSE_SAMPLES):
        return rows
    with open(CLAUSE_SAMPLES, "r", encoding="utf-8") as f:
        samples = json.load(f)
    for sample in samples:
        code = sample.get("standard_code", "")
        clause = sample.get("clause", "")
        try:
            text = kl.read_clause(code, clause) or ""
            error = ""
        except Exception as exc:  # noqa: BLE001
            text = ""
            error = f"{type(exc).__name__}: {exc}"
        rows.append({
            "standard_code": code,
            "clause": clause,
            "text_len": len(text),
            "text_head": text[:CLAUSE_FP_LEN],
            "error": error,
        })
    return rows


def build_snapshot():
    search_rows = _snapshot_search()
    return {
        "schema": 2,
        "kb_status": kl.status(),
        "aggregate": _aggregate_fingerprint(search_rows),
        "search": search_rows,
        "clauses": _snapshot_clauses(),
    }


def _strict_results_match(base_results, cur_results):
    """deterministic 分支: 除 score 外身份字段精确匹配, score 用容差。
    返回 (是否一致, 首个不一致下标或 None)。"""
    if len(base_results) != len(cur_results):
        return False, min(len(base_results), len(cur_results))
    for i, (b, c) in enumerate(zip(base_results, cur_results)):
        for key in ("file", "source", "heading", "standard_code", "confidence"):
            if b.get(key) != c.get(key):
                return False, i
        if abs(float(b.get("score", 0)) - float(c.get("score", 0))) > SCORE_TOLERANCE:
            return False, i
    return True, None


def _agg_diffs(base_agg, cur_agg):
    """比较聚合召回指纹; 超过容差则报漂移。守护 ppr+legacy 分支质量。"""
    diffs = []
    if not base_agg or not cur_agg:
        return diffs

    def cmp_block(label, b, c):
        for key in ("recall_at_5", "mrr", "ndcg"):
            bv, cv = b.get(key), c.get(key)
            if isinstance(bv, (int, float)) and isinstance(cv, (int, float)):
                if abs(bv - cv) > AGG_TOLERANCE:
                    diffs.append(f"[aggregate:{label}] {key}: {bv} -> {cv} (容差 {AGG_TOLERANCE})")
            elif bv != cv:
                diffs.append(f"[aggregate:{label}] {key}: {bv!r} -> {cv!r}")

    cmp_block("overall", base_agg, cur_agg)
    if base_agg.get("count") != cur_agg.get("count"):
        diffs.append(f"[aggregate] 评分查询数变化: {base_agg.get('count')} -> {cur_agg.get('count')}")
    if base_agg.get("ppr_branch") and cur_agg.get("ppr_branch"):
        cmp_block("ppr", base_agg["ppr_branch"], cur_agg["ppr_branch"])
    return diffs


def _diff(baseline, current):
    """返回人类可读的差异列表; 空列表表示一致。

    分支感知: deterministic 分支精确逐条比对 (score 容差); ppr+legacy 分支不做逐条
    身份断言 (跨进程不确定), 改由聚合召回指纹守护。忽略 kb_status 统计漂移。"""
    diffs = []

    # 聚合召回指纹 (ppr+legacy 分支的主要守护, 也覆盖整体召回质量)。
    diffs.extend(_agg_diffs(baseline.get("aggregate"), current.get("aggregate")))

    base_search = {r["query"]: r for r in baseline.get("search", [])}
    cur_search = {r["query"]: r for r in current.get("search", [])}

    for query in sorted(set(base_search) | set(cur_search)):
        b = base_search.get(query)
        c = cur_search.get(query)
        if b is None:
            diffs.append(f"[search] 新增查询: {query!r}")
            continue
        if c is None:
            diffs.append(f"[search] 缺失查询: {query!r}")
            continue
        if b.get("error") != c.get("error"):
            diffs.append(f"[search] {query!r} error: {b.get('error')!r} -> {c.get('error')!r}")

        base_branch = b.get("branch", "")
        cur_branch = c.get("branch", "")

        if base_branch in DETERMINISTIC_BRANCHES:
            # deterministic 分支: 分支翻转也是真实回归。
            if base_branch != cur_branch:
                diffs.append(f"[search] {query!r} 分支变化: {base_branch!r} -> {cur_branch!r}")
            ok, _ = _strict_results_match(b["results"], c["results"])
            if not ok:
                diffs.append(f"[search:{base_branch or 'det'}] {query!r} 结果漂移 (严格):")
                bl, cl = b["results"], c["results"]
                for i in range(max(len(bl), len(cl))):
                    bi = bl[i] if i < len(bl) else None
                    ci = cl[i] if i < len(cl) else None
                    if bi != ci:
                        diffs.append(f"    #{i + 1} base={_fmt(bi)}")
                        diffs.append(f"        cur ={_fmt(ci)}")
        else:
            # ppr+legacy 分支: 不做逐条身份断言 (聚合指纹守护)。
            # 仅捕获灾难性退化: 原本有结果, 现在变空/报错。
            if b.get("result_count", 0) > 0 and c.get("result_count", 0) == 0 and not c.get("error"):
                diffs.append(f"[search:{base_branch}] {query!r} 退化为空结果 "
                             f"({b.get('result_count')} -> 0)")

    base_clause = {(r["standard_code"], r["clause"]): r for r in baseline.get("clauses", [])}
    cur_clause = {(r["standard_code"], r["clause"]): r for r in current.get("clauses", [])}
    for key in sorted(set(base_clause) | set(cur_clause)):
        b = base_clause.get(key)
        c = cur_clause.get(key)
        if b is None or c is None:
            diffs.append(f"[clause] {key} 仅存在于一侧")
            continue
        if b.get("error") != c.get("error"):
            diffs.append(f"[clause] {key} error: {b.get('error')!r} -> {c.get('error')!r}")
        if b.get("text_head") != c.get("text_head") or b.get("text_len") != c.get("text_len"):
            diffs.append(f"[clause] {key} 条文漂移: len {b.get('text_len')} -> {c.get('text_len')}")
    return diffs


def _fmt(sig):
    if sig is None:
        return "<无>"
    return (f"file={sig['file']!r} src={sig['source']!r} "
            f"score={sig['score']} code={sig['standard_code']!r} conf={sig['confidence']!r}")


def main():
    parser = argparse.ArgumentParser(description="KBResolver 行为快照回归测试")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--update", action="store_true", help="生成/覆盖基线快照")
    args = parser.parse_args()

    try:
        current = build_snapshot()
    except Exception as exc:  # noqa: BLE001
        print(f"快照构建失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.update:
        os.makedirs(os.path.dirname(args.baseline), exist_ok=True)
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        n_q = len(current["search"])
        n_c = len(current["clauses"])
        print(f"基线已写入 {args.baseline} (查询 {n_q} 条, 条款 {n_c} 条)")
        return 0

    if not os.path.exists(args.baseline):
        print(f"基线不存在: {args.baseline}\n先运行: python eval/snapshot_regression.py --update",
              file=sys.stderr)
        return 2

    with open(args.baseline, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    diffs = _diff(baseline, current)
    if not diffs:
        print(f"快照一致 ✓ (查询 {len(current['search'])} 条, 条款 {len(current['clauses'])} 条)")
        return 0
    print(f"检测到 {len(diffs)} 处行为漂移:\n")
    for line in diffs:
        print(line)
    print("\n若漂移是预期内的, 用 --update 刷新基线。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
