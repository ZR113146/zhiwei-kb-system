# -*- coding: utf-8 -*-
"""pipeline 索引产物特征化测试 (5.2/5.3 改造的安全网)。

覆盖 5.2(路径治理)/5.3(PPR 修图)将改动的 pipeline 构建脚本: 重建各产物 →
剔除易变元数据(_meta 里的时间戳) → 对内容规范化(sort_keys)后做 SHA 指纹。
重构前后比对, 任何索引内容漂移都会被捕获。

为何剔 _meta: kb_search_index 等产物的 _meta.updated 是构建时间戳, 裸 SHA 每次都变;
索引内容(index/_files/...)本身跨进程确定(已实测)。指纹只锁内容, 不锁时间戳。

注意: 每个脚本重建会覆盖正式运行时产物(本来就是它们的职责, 非降级版,
不污染——区别于 KBResolver._rebuild_index_lite 那种精简重建)。重建耗时较长。

用法:
  生成基线: python eval/pipeline_index_snapshot.py --update
  回归对比: python eval/pipeline_index_snapshot.py
  指定脚本: python eval/pipeline_index_snapshot.py --only kb_search_index
退出码: 0 = 一致 / 基线已写; 1 = 漂移; 2 = 运行错误。
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline")
KB_JSON = os.path.join(ROOT, "data", "kb_json")
DEFAULT_BASELINE = os.path.join(ROOT, "eval", "pipeline_index_baseline.json")

# 每个脚本: (构建命令 args, 产物文件名)。命令相对 pipeline/ 目录跑。
# kb_term_index 无参=全量(--incremental 才是增量); kb_body_bm25 段落索引重, 需长超时。
TARGETS = {
    "kb_search_index": (["kb_search_index.py", "--full"], "kb_search_index.json"),
    "kb_term_index": (["kb_term_index.py"], "kb_term_index.json"),
    "kb_body_bm25": (["kb_body_bm25.py"], "kb_body_bm25.json"),
    "kb_build_phrase_model": (["kb_build_phrase_model.py"], "kb_phrase_model.json"),
}
BUILD_TIMEOUT = 580  # kb_body_bm25 段落BM25较重


def _strip_volatile(obj):
    """递归剔除易变元数据: 顶层/嵌套的 _meta.updated 等时间戳字段。
    保留 _meta 里的稳定计数(total_files 等)。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("updated", "generated_at", "timestamp", "build_time", "date"):
                continue  # 时间戳, 跳过
            out[k] = _strip_volatile(v)
        return out
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    return obj


def _fingerprint(product_path):
    """产物内容指纹: 剔时间戳 → 规范化(sort_keys) → SHA256。"""
    with open(product_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cleaned = _strip_volatile(data)
    blob = json.dumps(cleaned, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _build(args):
    """跑构建脚本 (cwd=pipeline)。返回 (ok, err)。"""
    try:
        r = subprocess.run(
            [sys.executable] + args,
            cwd=PIPELINE, capture_output=True, text=True, timeout=BUILD_TIMEOUT,
            encoding="utf-8", errors="replace",  # 子进程中文输出: 强制 UTF-8 解码, 不崩
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return r.returncode == 0, (r.stderr or "")[-300:]
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def build_snapshot(only=None):
    rows = {}
    for name, (args, product) in TARGETS.items():
        if only and name != only:
            continue
        ok, err = _build(args)
        product_path = os.path.join(KB_JSON, product)
        if not ok:
            rows[name] = {"error": "build failed: " + err}
            continue
        if not os.path.exists(product_path):
            rows[name] = {"error": "product missing: " + product}
            continue
        rows[name] = {
            "product": product,
            "sha256": _fingerprint(product_path),
            "error": "",
        }
    return rows


def _diff(baseline, current):
    diffs = []
    for name in sorted(set(baseline) | set(current)):
        b = baseline.get(name)
        c = current.get(name)
        if b is None:
            diffs.append(f"新增脚本: {name}")
        elif c is None:
            diffs.append(f"缺失脚本: {name}")
        elif b != c:
            diffs.append(f"{name}: sha {str(b.get('sha256'))[:12]} -> {str(c.get('sha256'))[:12]} "
                         f"err {b.get('error')!r} -> {c.get('error')!r}")
    return diffs


def main():
    parser = argparse.ArgumentParser(description="pipeline 索引产物特征化回归")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--only", default=None, help="只测某个脚本")
    args = parser.parse_args()

    current = build_snapshot(only=args.only)
    if not current:
        print("无目标脚本", file=sys.stderr)
        return 2

    if args.update:
        # 增量更新: 保留未重建的脚本基线
        base = {}
        if os.path.exists(args.baseline):
            with open(args.baseline, "r", encoding="utf-8") as f:
                base = json.load(f)
        base.update(current)
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, indent=2)
        print(f"基线已写入 {args.baseline}:")
        for name, row in current.items():
            print(f"  {name}: {row.get('sha256','')[:12] or row.get('error')}")
        return 0

    if not os.path.exists(args.baseline):
        print(f"基线不存在: {args.baseline}\n先 --update", file=sys.stderr)
        return 2
    with open(args.baseline, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    diffs = _diff({k: baseline[k] for k in current if k in baseline}, current)
    if not diffs:
        print(f"特征化一致 ✓ ({', '.join(current)})")
        return 0
    print(f"检测到 {len(diffs)} 处漂移:")
    for line in diffs:
        print(" ", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
