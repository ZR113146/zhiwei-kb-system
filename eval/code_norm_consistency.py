# -*- coding: utf-8 -*-
"""标准编号归一化 —— 多入口一致性回归 (single-source-of-truth 守护)。

用法:  py eval/code_norm_consistency.py
退出码: 0 全部一致 | 1 有入口漂移 | 2 加载失败

目的: 锁死"全项目所有归一化入口对同一输入产出同一 canonical",
      使未来任何人再写第 N 个私有正则/漏传播修复时立即红灯。

两个 suite:
  A. normalize 契约: 输入=码 token, 断言 -> 期望 canonical
  B. extract   契约: 输入=文件名/文本, 抽码后归一 -> 期望 canonical

阶段3待接入 (重建产物后再验): pipeline.kb_clause_index / kb_ppr_graph /
build_index 的内联抽取器 —— 见 [[归一化统一化方案]]。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

from kb_core.code_norm import normalize_code as CANON, extract_standard  # noqa: E402


# ── 形态矩阵: 输入 -> 期望 canonical ────────────────────────────
# 覆盖: 前缀族 × 分隔符(/ _ 空格 全角 紧凑) × 有无年份 × 有无 /T
CANON_MATRIX = {
    "GB/T 50720-2011": "GBT50720",
    "GB_T 50720-2011": "GBT50720",
    "GB_T50720": "GBT50720",
    "GBT50720": "GBT50720",
    "GB／T50720": "GBT50720",         # 全角斜杠
    "GB 50204-2015": "GB50204",
    "GB50011": "GB50011",
    "JGJ/T 79-2012": "JGJT79",
    "JGJ 79-2012": "JGJ79",
    "CJJ_T 287-2018": "CJJT287",
    "CJJ/T 287-2018": "CJJT287",
    "CECS 164-2004": "CECS164",
    "DB32/T 3700-2019": "DB32T3700",
    "JC/T 547-2017": "JCT547",
}

# 历史 bug 锚点 (勿再退化)
ANCHORS = {
    "GB_T50720": "GBT50720",          # 下划线不能变 None
    "GB/T 50720-2011": "GBT50720",    # 年份不能粘成 507202011
    "GB/T50720": "GBT50720",          # /T 不能丢 T -> GB50720
}

# extract 契约输入 (文件名/文本) -> 期望 canonical
EXTRACT_MATRIX = {
    "_seg0_GB_T 50720-2011 建设工程施工现场消防安全技术标准(2025 年版).md": "GBT50720",
    "_seg1_JGJ 79-2012 建筑地基处理技术规范_p0001-0128.md": "JGJ79",
    "_seg0_CJJ_T 287-2018 园林绿化养护标准.md": "CJJT287",
    "GB 50204-2015 混凝土结构工程施工质量验收规范": "GB50204",
}


def _canonize(value):
    """把任意入口的返回(码字符串/None/dict)统一折算成 canonical。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("standard_code", "")
    return CANON(str(value))


def _load_entries():
    """收集 phase 0-2 范围内所有归一化入口。返回 {suite: {name: fn}}。"""
    A, B = {}, {}

    # 真源
    A["code_norm.normalize_code"] = CANON

    from kb_core.resolver import _common as C
    A["_common.normalize_code"] = C.normalize_code
    A["_common.normalize_status_code"] = C.normalize_status_code

    def _parse_canon(x):
        p = C.parse_standard_code(x)
        return C.canonicalize_code(p) if p else ""
    A["_common.parse+canonicalize"] = _parse_canon

    from kb_core import support_guard as SG
    A["support_guard.compact_code"] = SG.compact_code

    from kb_core import server as SV
    A["server._normalize_ref_code"] = SV._normalize_ref_code

    from kb_core import kb_ppr_engine as PE
    A["ppr._normalize_code"] = PE._normalize_code

    # extract 契约
    B["code_norm.extract_standard"] = extract_standard
    B["ppr._extract_code"] = PE._extract_code
    try:
        from pipeline import pipeline_orchestrator as PO
        B["orchestrator.extract_code"] = PO.extract_code
    except Exception:
        pass
    try:
        from pipeline import kb_image_index as II
        B["image_index.extract_code_from_filename"] = II.extract_code_from_filename
    except Exception:
        pass
    # 阶段3 构建器抽取器 (委托后应收敛)
    try:
        from pipeline import kb_ppr_graph as PG  # noqa: F401
        # kb_ppr_graph.extract_code 是 _add_bm25_edges 内的闭包, 无法直接取;
        # 改测其底层 _cn_extract (已委托 code_norm), 作为该文件抽取一致性的锚。
        B["ppr_graph._cn_extract"] = lambda x: (PG._cn_extract(x) or {}).get("standard_code", "")
    except Exception:
        pass

    return {"A": A, "B": B}


def _run_suite(entries, matrix, extract=False):
    """返回 (all_ok, [(entry, input, got, expect), ...] 漂移列表)。"""
    drift = []
    for name, fn in entries.items():
        for inp, expect in matrix.items():
            try:
                got = _canonize(fn(inp)) if extract else _canonize(fn(inp))
            except Exception as e:
                got = f"<EXC:{type(e).__name__}>"
            if got != expect:
                drift.append((name, inp, got, expect))
    return (not drift), drift


def main():
    try:
        suites = _load_entries()
    except Exception as e:
        print(f"[LOAD-ERROR] {type(e).__name__}: {e}")
        return 2

    # 0) 真源自检 (矩阵 + 锚点)
    src_fail = []
    for inp, expect in {**CANON_MATRIX, **ANCHORS}.items():
        got = CANON(inp)
        if got != expect:
            src_fail.append((inp, got, expect))
    for inp, expect in EXTRACT_MATRIX.items():
        got = _canonize(extract_standard(inp))
        if got != expect:
            src_fail.append((inp, got, expect))
    if src_fail:
        print("[SRC-FAIL] code_norm 真源矩阵不达标:")
        for inp, got, exp in src_fail:
            print(f"   {inp!r:30} got={got!r:14} expect={exp!r}")
        return 1
    print(f"[OK] 真源矩阵通过 ({len(CANON_MATRIX)+len(ANCHORS)+len(EXTRACT_MATRIX)} 例)")

    # A) normalize 契约多入口一致性
    okA, driftA = _run_suite(suites["A"], {**CANON_MATRIX, **ANCHORS})
    # B) extract 契约多入口一致性
    okB, driftB = _run_suite(suites["B"], EXTRACT_MATRIX, extract=True)

    print(f"\nSuite A (normalize契约, {len(suites['A'])} 入口): {'OK' if okA else 'DRIFT'}")
    print(f"Suite B (extract契约,   {len(suites['B'])} 入口): {'OK' if okB else 'DRIFT'}")

    if driftA or driftB:
        print("\n=== 漂移明细 (待收敛入口) ===")
        for name, inp, got, exp in driftA + driftB:
            print(f"   {name:34} {inp!r:24} got={got!r:14} expect={exp!r}")
        return 1

    print("\n[ALL GREEN] 所有归一化入口收敛到单一真源。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
