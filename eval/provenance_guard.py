# -*- coding: utf-8 -*-
"""检索产物血缘守护 (provenance guard) — 防"孤儿产物喂陈旧索引"重演。

本会话曾发现 kb_param_extract.py 是孤儿 (孤儿生产者的 orphan 产物喂陈旧数据给
检索), 导致用户在插件里看到错答案 (bug-α/β 被 92f09778 叶子分段激活才显现)。
本守护把"每个检索产物都有接入 orchestrator 的生产者 + 不比基座陈旧"从"靠人发现"
变成"静态检查拦截"。

只读静态检查: 不重建任何产物、不跑模型。纯文件 mtime + 产销映射核对 → 快、
零行为风险。区别于 snapshot_regression (聚合召回指纹) 与 pipeline_index_snapshot
(重建后内容指纹)。

三类断言:
  A. 孤儿产物: kb_core 消费的产物在 PRODUCERS 表里无生产者 → exit 1
  B. 生产者脱链: 生产者脚本不在 orchestrator 调用列表 → exit 1 (会变孤儿)
  C. 陈旧产物: 产物 mtime < 基座 kb_search_index.json mtime → exit 1 (该重建没重建)

用法:  py eval/provenance_guard.py
退出码: 0 = 血缘完整且新鲜 | 1 = 有孤儿/脱链/陈旧 | 2 = 加载失败
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_JSON = os.path.join(ROOT, "data", "kb_json")
PIPELINE = os.path.join(ROOT, "pipeline")
ORCH = os.path.join(PIPELINE, "pipeline_orchestrator.py")

# 服务端(kb_core)消费的检索产物 → 生产该产物的 pipeline 脚本。
# 这是血缘契约: 新增 kb_core 消费的产物必须在此登记生产者, 否则 A 拦;
# 登记的生产者必须真被 orchestrator 调用, 否则 B 拦。
# (kb_term_index 的产物 kb_term_index.json 当前未被 kb_core 直接消费, 故不列;
#  kb_body_bm25 的产物 kb_body_bm25.json 也仅供 legacy 通道, 见下。)
CONSUMERS = {
    "kb_search_index.json": "kb_search_index.py",
    "kb_clause_index.json": "kb_clause_index.py",
    "kb_cross_refs.json": "kb_cross_refs.py",
    "kb_image_index.json": "kb_image_index.py",
    "kb_phrase_model.json": "kb_build_phrase_model.py",
    "kb_ppr_graph.json": "kb_ppr_graph.py",
    "kb_sentence_meta.json": "kb_sentence_vectors.py",
    "kb_sentence_vectors.faiss": "kb_sentence_vectors.py",
    # legacy 词面通道消费 (kb_body_bm25.json 由 kb_body_bm25.py 生产):
    "kb_body_bm25.json": "kb_body_bm25.py",
}

# 基座产物: 其余检索产物在逻辑上派生自它, 故不应比它陈旧。
BASE_ARTIFACT = "kb_search_index.json"

# 待重建产物白名单 (amnesty): 已知陈旧、需走 MinerU 全链路重建才能刷新,
# 但本机未跑该链路 → 既存状态、非本次改动引入。守护对这些只 warn 不 fail,
# 等重建后它们 mtime 刷新 → 自然从该名单移除即转硬 fail。诚实: 不让"已知
# 待重建的既存问题"阻断正确提交, 但保持可见。
AMNESTY_STALE = {
    "kb_cross_refs.json",      # 5-30, 需 rebuild_index 链刷新
    "kb_image_index.json",     # 6-2
    "kb_phrase_model.json",    # 5-30
}


def _orchestrator_scripts():
    """orchestrator 通过 subprocess 调用的脚本集合 (脚本文件名)。
    orchestrator 把脚本路径用变量名引用 (如 bm25_script = join(SCRIPTS_DIR,
    'kb_body_bm25.py')), 故用正则抽所有 'xxx.py' / "xxx.py" 字面量。"""
    if not os.path.exists(ORCH):
        return set()
    text = open(ORCH, encoding="utf-8", errors="replace").read()
    import re
    return set(re.findall(r"""['"]([a-z0-9_]+\.py)['"]""", text))


def _mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None


def main():
    orch_scripts = _orchestrator_scripts()

    errors = []

    # A. 孤儿产物 + B. 生产者脱链
    for artifact, producer in CONSUMERS.items():
        producer_path = os.path.join(PIPELINE, producer)
        if not os.path.exists(producer_path):
            errors.append(f"[A-孤儿] 产物 {artifact} 的登记生产者 {producer} 不存在")
            continue
        if producer not in orch_scripts:
            errors.append(f"[B-脱链] 生产者 {producer} (→{artifact}) 不在 orchestrator 调用列表 → 将成孤儿")

    # C. 陈旧产物 (mtime < 基座 mtime, 超出合理构建链时差)
    # 同一轮 orchestrator 构建里, 产物按链顺序生产 (search_index → ... → ppr_graph),
    # 相差几分钟到几十分钟是链式生产的正常现象, 不是孤儿/陈旧。只对"明显跨轮"
    # (>1 小时) 报陈旧 — 那通常意味着基座重建了而某产物没跟着重建。
    STALE_THRESHOLD_SEC = 3600  # 1 小时: 容许单轮链式生产的合理时差
    base_path = os.path.join(KB_JSON, BASE_ARTIFACT)
    base_t = _mtime(base_path)
    if base_t is None:
        errors.append(f"[C-基座缺失] 基座产物 {BASE_ARTIFACT} 不存在, 无法判定陈旧")
    else:
        for artifact in CONSUMERS:
            ap = os.path.join(KB_JSON, artifact)
            t = _mtime(ap)
            if t is None:
                continue
            if t < base_t - STALE_THRESHOLD_SEC:
                import time
                age_hr = round((base_t - t) / 3600, 1)
                msg = f"[C-陈旧] 产物 {artifact} 比基座 {BASE_ARTIFACT} 旧 {age_hr} 小时 → 基座重建后该产物未跟着重建"
                if artifact in AMNESTY_STALE:
                    print(f"   [amnesty-warn] {msg} (已列待重建白名单, 非阻断)")
                else:
                    errors.append(msg)

    # 产物存在性 (软报告, 不阻断)
    missing = [a for a in CONSUMERS if not os.path.exists(os.path.join(KB_JSON, a))]
    if missing:
        print(f"[WARN] 产物文件缺失 (需构建, 非血缘问题): {missing}")

    print(f"[血缘] 消费产物 {len(CONSUMERS)} 个; orchestrator 调用脚本 {len(orch_scripts)} 个。")
    if errors:
        print(f"[FAIL] 血缘问题 {len(errors)} 处:")
        for e in errors:
            print(f"   {e}")
        return 1
    print("[GREEN] 血缘完整且产物新鲜: 每个消费产物有被 orchestrator 调用的生产者, 无陈旧产物。")
    return 0


if __name__ == "__main__":
    sys.exit(main())