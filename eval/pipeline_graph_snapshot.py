# -*- coding: utf-8 -*-
"""build_graph 重构特征化测试 (Step 2 安全网)。

build_graph (pipeline/kb_ppr_graph.py) 构建 search 依赖的 PPR 图。它读 4 个索引
(phrase_model / term_index / search_index / body_bm25) 产出 edges。本脚本对其输出
做确定性指纹, 用于重构前后逐字节对比, 确保拆分纯属重构、行为不变。

注意: 加载 ~70MB 索引, 单次运行约数十秒。

用法:
  生成基线: python eval/pipeline_graph_snapshot.py --update
  回归对比: python eval/pipeline_graph_snapshot.py
退出码: 0 = 一致 / 基线已写; 1 = 漂移; 2 = 运行错误。
"""

import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline")
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

DEFAULT_BASELINE = os.path.join(ROOT, "eval", "pipeline_graph_baseline.json")


def _build_graph_output():
    import kb_ppr_graph as g
    pm = g.load_phrase_model()
    ti = g.load_term_index()
    si = g.load_search_index()
    bi = g.load_bm25_index()
    return g.build_graph(pm, ti, si, bi)


def build_snapshot():
    graph = _build_graph_output()
    # edges 是 list[list[(tgt, w_int)]]; 序列化为稳定字符串再哈希。
    edges = graph["edges"]
    edges_blob = json.dumps(edges, sort_keys=False, separators=(",", ":"))
    edges_sha = hashlib.sha256(edges_blob.encode("utf-8")).hexdigest()
    words_sha = hashlib.sha256(
        json.dumps(graph["words"], ensure_ascii=False).encode("utf-8")).hexdigest()
    files_sha = hashlib.sha256(
        json.dumps(graph["files"], ensure_ascii=False).encode("utf-8")).hexdigest()
    total_edges = sum(len(r) for r in edges)
    tf_edges = sum(1 for r in edges for tgt, _ in r if tgt >= graph["n_terms"])
    return {
        "schema": 1,
        "n_terms": graph["n_terms"],
        "n_files": graph["n_files"],
        "total": graph["total"],
        "total_edges": total_edges,
        "tf_edges": tf_edges,
        "tt_edges": total_edges - tf_edges,
        "edge_counts_by_type": graph["edge_counts_by_type"],
        "edges_sha256": edges_sha,
        "words_sha256": words_sha,
        "files_sha256": files_sha,
    }


def _diff(baseline, current):
    diffs = []
    for key in sorted(set(baseline) | set(current)):
        if key == "schema":
            continue
        if baseline.get(key) != current.get(key):
            diffs.append(f"{key}: {baseline.get(key)!r} -> {current.get(key)!r}")
    return diffs


def main():
    parser = argparse.ArgumentParser(description="build_graph 特征化回归")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    try:
        current = build_snapshot()
    except Exception as exc:  # noqa: BLE001
        print(f"快照构建失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.update:
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        print(f"基线已写入 {args.baseline}")
        print(f"  total_edges={current['total_edges']:,} "
              f"edges_sha={current['edges_sha256'][:12]}")
        return 0

    if not os.path.exists(args.baseline):
        print(f"基线不存在: {args.baseline}\n先运行 --update", file=sys.stderr)
        return 2

    with open(args.baseline, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    diffs = _diff(baseline, current)
    if not diffs:
        print(f"特征化一致 ✓ (total_edges={current['total_edges']:,}, "
              f"edges_sha={current['edges_sha256'][:12]})")
        return 0
    print(f"检测到 {len(diffs)} 处漂移:")
    for line in diffs:
        print(" ", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
