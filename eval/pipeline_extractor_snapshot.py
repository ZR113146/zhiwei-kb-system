# -*- coding: utf-8 -*-
"""extract_high_conf_headings 重构特征化测试 (Step 2 安全网)。

extract_high_conf_headings / build_graph 是离线索引构建代码, 不被 search 快照覆盖。
本脚本对一批真实 MinerU JSON 跑 extract_high_conf_headings, 把输出指纹化, 用于
重构前后逐字节对比, 确保拆分纯属重构、行为不变。

用法:
  生成基线: python eval/pipeline_extractor_snapshot.py --update
  回归对比: python eval/pipeline_extractor_snapshot.py
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

from kb_heading_extractor import extract_high_conf_headings  # noqa: E402

KB_JSON = os.path.join(ROOT, "data", "kb_json")
DEFAULT_BASELINE = os.path.join(ROOT, "eval", "pipeline_extractor_baseline.json")
SAMPLE_SIZE = 40  # 取前 N 个 (按文件名排序, 确定性)


def _sample_files():
    if not os.path.isdir(KB_JSON):
        return []
    files = sorted(f for f in os.listdir(KB_JSON)
                   if f.endswith(".json") and f != "manifest.json")
    return files[:SAMPLE_SIZE]


def build_snapshot():
    rows = []
    for fname in _sample_files():
        path = os.path.join(KB_JSON, fname)
        try:
            headings = extract_high_conf_headings(path)
            # 输出规范化为稳定字符串再哈希, 避免巨大基线文件。
            blob = json.dumps(headings, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
            rows.append({
                "file": fname,
                "count": len(headings),
                "sha256": digest,
                "error": "",
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({"file": fname, "count": -1, "sha256": "", "error": f"{type(exc).__name__}: {exc}"})
    return {"schema": 1, "sample_size": len(rows), "rows": rows}


def _diff(baseline, current):
    diffs = []
    base = {r["file"]: r for r in baseline.get("rows", [])}
    cur = {r["file"]: r for r in current.get("rows", [])}
    for fname in sorted(set(base) | set(cur)):
        b, c = base.get(fname), cur.get(fname)
        if b is None:
            diffs.append(f"新增文件: {fname}")
        elif c is None:
            diffs.append(f"缺失文件: {fname}")
        elif b != c:
            diffs.append(f"{fname}: count {b['count']}->{c['count']} "
                         f"sha {b['sha256'][:8]}->{c['sha256'][:8]} err {b['error']!r}->{c['error']!r}")
    return diffs


def main():
    parser = argparse.ArgumentParser(description="extract_high_conf_headings 特征化回归")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    try:
        current = build_snapshot()
    except Exception as exc:  # noqa: BLE001
        print(f"快照构建失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not current["rows"]:
        print("无样本输入 (data/kb_json 为空?)", file=sys.stderr)
        return 2

    if args.update:
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        print(f"基线已写入 {args.baseline} (样本 {current['sample_size']} 个)")
        return 0

    if not os.path.exists(args.baseline):
        print(f"基线不存在: {args.baseline}\n先运行 --update", file=sys.stderr)
        return 2

    with open(args.baseline, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    diffs = _diff(baseline, current)
    if not diffs:
        print(f"特征化一致 ✓ (样本 {current['sample_size']} 个)")
        return 0
    print(f"检测到 {len(diffs)} 处漂移:")
    for line in diffs:
        print(" ", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
