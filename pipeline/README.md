# pipeline/ — 知识库构建流水线

本目录是知微 KB 的**离线构建流水线**：把 PDF 规范变成可检索的多重索引
（MD 正文库、搜索索引、术语/短语/BM25/条款/交叉引用索引、向量库）。

入口是 **`pipeline_orchestrator.py`** —— 一个相位锁定（phase-locked）、以
`session.json` 为唯一真相源、幂等可重入的 4-Phase 编排器。它通过 `subprocess`
调用下面各专用脚本，因此在静态依赖图里它的 import fan-in 看似为 0，实则是真正
的总调度入口。

> 说明：本文件是**执行顺序图 + 脚本分类**的文档，不改变任何行为。`data/`、
> `projects/` 等运行时产物已在 `.gitignore`。

---

## 一、主流程：`pipeline_orchestrator.py`

```
python pipeline_orchestrator.py "PDF目录"      # 全流程 A→B→C→D
python pipeline_orchestrator.py --resume       # 断点恢复（向量监听超时后续跑）
python pipeline_orchestrator.py --phase c      # 单独跑某个 Phase
```

各 Phase 实际驱动的脚本（按调用顺序）：

| Phase | 职责 | 依次调用的脚本（subprocess） |
|---|---|---|
| **A** 去重+预检+切割 | 文件名校验、PDF 去重、按页切块 | `kb_validate_filenames.py` → `split_pdfs.py` |
| **B** 提取 | MinerU 批量解析 PDF→JSON | `batch_extract.py --all` |
| **C1** 导入+索引 | MD 导入、增量构建各索引、等待向量嵌入 | `kb_import.py` → `kb_search_index.py --incremental` → `kb_term_index.py` → `kb_build_phrase_model.py` → `kb_body_bm25.py` → `kb_clause_index.py` → `kb_cross_refs.py` → `kb_image_index.py` → `kb_watch_vectors.py` |
| **C2** 合并+建库 | 条款级 JSON 索引构建、浮动标签评分 | `build_index.py --incremental` → `tag_scorer.py` |
| **D** 验证+清理+归档 | 端到端抽查、三库完整性、搜索质量门、清理 staging | `kb_e2e_verify.py` → `kb_verify_integrity.py --alert` → `kb_search_quality.py --check` |

C1 末尾的向量嵌入是**人工门**：嵌入完成（或超时）后 C1 退出，
`--resume --phase c` 继续 C2。质量门（D2/D2.5）不通过则**拒绝清理**、保留
staging 供修复。

> 注：`kb_ppr_graph.py`（PPR 图）自 v6.24 起已从在线搜索下架，**不再由
> orchestrator 自动重建**；如需重建见下方"手动工具"。

---

## 二、脚本分类

### 1. 流水线被调脚本（由 orchestrator 驱动，一般不单独跑）
- `kb_validate_filenames.py` — G0 文件名规范校验（不合规阻断入库）
- `split_pdfs.py` — PDF 按页切块
- `batch_extract.py` — MinerU 批量提取（`--retry-failed` 重试失败块）
- `kb_import.py` — JSON→MD 正文库导入
- `kb_search_index.py` — 搜索索引（标题+段落）
- `kb_term_index.py` — 术语注入索引
- `kb_build_phrase_model.py` — 短语模型（含 term_map 白名单）
- `kb_body_bm25.py` — 段落级 BM25 索引
- `kb_clause_index.py` — 条款编号索引（精确查询直通车）
- `kb_cross_refs.py` — 跨标准引用索引
- `kb_image_index.py` — 图片元数据索引
- `kb_watch_vectors.py` — 向量嵌入监听
- `build_index.py` — 规范条款级 JSON 索引构建（`kb.json` 的 `build_index_script`）
- `tag_scorer.py` — 浮动标签评分（消费搜索日志）

### 2. 向量库构建（BGE-M3，按需离线运行）
- `kb_sentence_extract.py` — 从 MD 提取句子文本
- `kb_sentence_vectors.py` — 句子向量 FAISS 索引
- `kb_word_vectors_v2.py` — V2 上下文词向量
- `kb_vector_search_local.py` — 运行时向量检索后端（FAISS C++），被 resolver 调用

### 3. PPR 图 / 词模型（实验/离线，非在线必需）
- `kb_ppr_graph.py` — PPR 统一图索引（v6.24 已下架，手动重建）
- `kb_ppr_grid_search.py` — PPR 参数网格搜索
- `kb_ppr_quality.py` — PPR 传播质量门
- `kb_bigram_model.py` — Bigram 语言模型
- `kb_term_bge_augment.py` — BGE 词向量辅助术语映射扩展
- `tag_trainer_v3.py` — 浮动标签训练器（AI 生成查询）

### 4. 抽取辅助（被上面脚本 import 或按需）
- `kb_heading_extractor.py` — 高置信度标题提取（被 `kb_search_index.py` 调用）
- `kb_param_extract.py` — 高频参数→数值→条款映射
- `kb_table_merge.py` — MinerU 跨页分表合并

### 5. 验证 / 运维 / 反馈（独立运行）
- `kb_e2e_verify.py` — 端到端抽查
- `kb_verify_integrity.py` — 三库一致性校验
- `kb_search_quality.py` — 搜索质量门（用例评估+基线比对）
- `kb_self_test.py` — 关键路径集成测试（A→D 全管线）
- `kb_current_state.py` — 生成当前状态报告
- `kb_rollback.py` — 按会话回滚（含 manifest 快照恢复）
- `kb_feedback_processor.py` / `kb_feedback_report.py` — 反馈日志处理/汇总

---

## 三、典型操作

```bash
# 新规范入库（最常用）
python pipeline_orchestrator.py "D:\待入库PDF"

# 入库中断后恢复
python pipeline_orchestrator.py --resume

# 入库后回滚某次会话
python kb_rollback.py <session_id>

# 全管线自检
python kb_self_test.py

# 重建 PPR 图（已从在线下架，仅实验需要时）
python kb_ppr_graph.py
```
