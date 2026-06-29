# -*- coding: utf-8 -*-
"""数值冲突检测特征化测试 (E5 合并的安全网)。

E5: verify.check_value_conflicts 与 scan_docx 内联的跨章数值冲突检测是重复实现。
合并前先固化两者对一批构造文本的输出指纹, 合并后比对, 确保行为保持。

测 verify.check_value_conflicts(可直接调) + scan 的冲突检测逻辑(经 scan_docx,
但它要 docx; 故这里对 verify 版做精确特征化, scan 版合并时以其逻辑为蓝本,
两边各传自己的 key 子集——合并目标是行为保持, verify 输出不变即达标)。

用法:
  生成基线: python eval/plan_writer_conflict_snapshot.py --update
  回归对比: python eval/plan_writer_conflict_snapshot.py
退出码: 0=一致/已写; 1=漂移; 2=运行错误。
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in ("plan_writer",):
    p = os.path.join(ROOT, rel)
    if p not in sys.path:
        sys.path.insert(0, p)

DEFAULT_BASELINE = os.path.join(ROOT, "eval", "plan_writer_conflict_baseline.json")

# 构造测试文本: 覆盖 verify 各 key 的命中/冲突/单位归一/无冲突。
# (页号, 文本) — 用实测能命中 verify 正则的真实格式。
CASES = {
    "养护_冲突": [(1, "养护不应少7天的要求"), (2, "养护时间不应少14天")],
    "养护_无冲突": [(1, "养护不应少7天")],
    "压实_冲突": [(1, "压实系数不小于0.95"), (2, "压实系数不小于0.97")],
    "压实_同值": [(1, "压实系数不小于0.95"), (2, "压实系数≥0.95")],
    "开挖_单位归一": [(1, "最大开挖深度1.5m"), (2, "开挖深度1500mm")],
    "开挖_真冲突": [(1, "开挖深度3m"), (2, "开挖深度5m")],
    "灰缝_冲突": [(1, "灰缝10mm"), (2, "灰缝12mm")],
    "饱满度_冲突": [(1, "饱满度80%"), (2, "饱满度90%")],
    "成活率_冲突": [(1, "成活率95%"), (2, "成活率98%")],
    "空输入": [],
    "无关文本": [(1, "本工程位于江苏省南京市")],
}


def _fingerprint_verify():
    from verify import check_value_conflicts
    out = {}
    for name, all_text in CASES.items():
        try:
            issues = check_value_conflicts(all_text)
            # 规范化: 只取稳定字段, 排序
            norm = sorted([(i.get("detail", ""), i.get("severity", "")) for i in issues])
        except Exception as exc:  # noqa: BLE001
            norm = [("ERROR", f"{type(exc).__name__}: {exc}")]
        out[name] = norm
    return out


def build_snapshot():
    return {"schema": 1, "verify_check_value_conflicts": _fingerprint_verify()}


def _diff(baseline, current):
    # 经 JSON round-trip 规范化两边 (tuple→list 统一), 避免 list!=tuple 误报。
    baseline = json.loads(json.dumps(baseline, ensure_ascii=False))
    current = json.loads(json.dumps(current, ensure_ascii=False))
    diffs = []
    b = baseline.get("verify_check_value_conflicts", {})
    c = current.get("verify_check_value_conflicts", {})
    for name in sorted(set(b) | set(c)):
        if b.get(name) != c.get(name):
            diffs.append(f"{name}: {b.get(name)} -> {c.get(name)}")
    return diffs


def main():
    parser = argparse.ArgumentParser(description="数值冲突检测特征化回归")
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
        print(f"基线已写入 {args.baseline} ({len(CASES)} 例)")
        return 0

    if not os.path.exists(args.baseline):
        print(f"基线不存在: {args.baseline}\n先 --update", file=sys.stderr)
        return 2
    with open(args.baseline, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    diffs = _diff(baseline, current)
    if not diffs:
        print(f"特征化一致 ✓ ({len(CASES)} 例)")
        return 0
    print(f"检测到 {len(diffs)} 处漂移:")
    for line in diffs:
        print(" ", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
