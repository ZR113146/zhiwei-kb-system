# 知微 KB 系统 — 全面普筛裁决表

> 第 1 步产物。86 个 .py + 配置/契约全覆盖。4 个子代理分区并行排查 + 主控亲自核实高影响项。
> 裁决口径：`删`=死孤儿/零价值；`归档`=一次性工具有参考价值；`改`=失效/重叠/缺陷，**留给框架改造（第5步）**；`留`=健康。
> 原则：本表只标裁决，第 2 步只执行无争议的"删/归档"，所有"改"项等框架设计冻结后第 5 步统一处理。

## 一、跨切面发现（最重要，影响框架设计）

### 🔴 F1 — PPR 保留 + 修图重建【已决策：保留，消融纠错后翻转】

> ⚠️ **决策翻转记录**：先前基于消融数据定为"退役"，但那几轮消融**查询集选偏了**（偏 direct/param 精确型，PPR 本就不参与）。用 snapshot 完整查询集（92 条含 truth+技术查询）重测：**PPR 关闭后 recall@5 从 0.6087 稳定降到 0.5761（~3 点）**——PPR 对 NL/技术查询确有真实召回贡献，**非死重**。已纠正。

**决策：保留 PPR。** 改造方向从"退役"转为"修复加固"：
1. **修图重建**：让 `pipeline_orchestrator.py` 重新自动重建 `kb_ppr_graph.json`（解决 17 天旧图陈腐——新入库规范当前在 PPR 路径不可见）。
2. **解决线程非确定性**：`_run_nl_branch` 的 ThreadPool(legacy∥ppr) `as_completed` 完成顺序 + PPR 时序导致 ppr+legacy 分支 ~16% 跨进程漂移（见 zhiwei-kb-search-nondeterminism）。加固使其确定（如固定合并顺序、或串行化）。
3. PPR 簇脚本（kb_ppr_engine/kb_ppr_graph/grid_search/quality/term_bge_augment）**不归档、不删图、不清配置**。

**消融纠错教训**：① 头几轮用 100 条纯 golden（精确型为主），PPR 不生效的查询占多，误判"零贡献"；② monkeypatch `discover→[]` 与代码删除 `_run_ppr` 在 snapshot 全集上其实**结果一致（都 0.5761）**——证明删除本身正确，错的是"删除无害"的前提。③ snapshot 完整集（含技术查询子集）才覆盖到 PPR 真正生效的场景。**只用偏精确的查询集评估宽召回组件 = 系统性盲区。**

**仍存的代价（保留后要管理，非退役理由）**：17 天旧图（修图重建解决）、线程非确定性（加固解决）、12MB 图产物、多库时巨图与分库隔离的张力（未来多库时再评估，非当前阻碍）。

### 🟡 F2 — 数据/代码混杂普遍（~12 个 pipeline 脚本 + plan_writer 2 处）
用 `os.path.dirname(__file__)` 把运行态 JSON/jsonl 写进代码目录：`batch_failed.json`/`kb_search_log.jsonl`/`kb_tag_scores.json`/`kb_*_suggestions.json` 等；plan_writer 的 `standard_tags.json`/`project_type_map.json` 写死同目录读取。**这是"代码与产物拆不开"的根因**，框架改造的 contracts/ + data/ 分层要解决它。

### 🟡 F3 — 缺独立 contracts 层
源数据/契约散落：`kb_term_map*.json`(pipeline)、`standard_tags.json`(plan_writer)、`schemas/`(零代码加载的纯文档契约)、`kb.json`(配置真相源)。框架第3步应设计 contracts/ 层集中。

## 二、亲自核实的真实潜伏 bug（5 个，全部"改"，留给第5步）

| # | 位置 | 缺陷 | 触发条件 | 核实方式 |
|---|---|---|---|---|
| B1 | `kb_resolver_core.py:424` | 悬空 `@staticmethod` 错绑到 `_rebuild_index_lite(self)` | 仅 SEARCH_INDEX 缺失时崩(TypeError) | 实测 staticmethod+self 调用抛 TypeError；历史遗留(原始提交即有)，非重构引入 |
| B2 | `clause_refine.py:122` | `_rewrite_head_scores` 缺 `self` 形参 | 结果带 `_clause_sim` 走 clause 重排时崩 | 实测 `_clause_rerank` 抛 `takes 1 positional argument but 2 were given` |
| B3 | `clause_refine` 同上连带 | `_clause_rerank`("常开可靠底座")**当前静默失效** | 实测真实 NL 查询 top3 从不带 `_clause_sim`，重排路径从未真正生效 | 实测 3 条 NL 查询 `_clause_sim` 全 False |
| B4 | `pipeline_orchestrator.py:324` | subprocess 调 `kb_watch_vectors.py`，该文件全仓缺失，无 exists 兜底 | 跑完整 pipeline C1 阶段必崩 | 实测文件不存在 + grep 确认调用点 |
| B5 | `kb_auditor.py:22` | `_TERM_MAP_PATH` 指向不存在的 `pipeline/scripts/kb_term_map.json`(真实在 `pipeline/kb_term_map.json`)，被 os.path.exists 静默吞 | jieba 术语词典永不加载，v6.18 原文锚点提取静默退化 | 实测 scripts 子目录不存在 |

> 注：B1–B5 多为"叠加开发"留下的静默失效——不报错、但功能悄悄退化或在边界条件崩溃。这正是项目"没框架、打补丁累积"的代价。

## 三、无争议可立即处理（第2步候选）

### 删（死孤儿，零引用零价值）
| 文件 | 证据 |
|---|---|
| `kb_core/_test_suggest.py` | 全仓零 import，功能被 server/`__verify_chain` 覆盖 |

### 归档（一次性工具/实验，有参考价值，gitignore 或移 archive）
| 文件/簇 | 理由 |
|---|---|
| `kb_core/__verify_chain.py` | 临时验证脚本，已被 eval/snapshot_regression.py 取代，仅注释提及 |
| PPR 簇 `kb_ppr_engine`/`kb_ppr_graph`/`kb_ppr_grid_search`/`kb_ppr_quality`/`kb_term_bge_augment` | **F1 已翻转为保留**(消融纠错后证 PPR 有 ~3 点召回贡献)。**不归档**。改造方向：修图重建(orchestrator 自动重建 kb_ppr_graph)+ 解决线程非确定性。grid_search/quality/term_bge_augment 若确为一次性调参实验可单独评估归档，但 engine/graph 是活跃检索路径 |
| 向量构建 `kb_sentence_extract`/`kb_sentence_vectors`/`kb_word_vectors_v2` | 手动重建工具，产物部分仍在线消费，归档但留脚本 |
| `tag_trainer_v3`/`kb_table_merge` | 离线训练/数据清洗一次性工具 |
| plan_writer `build.py`/`patch.py`/`date_shift.py`/`diff_docx.py` | 零 import 的独立手动 CLI；diff_docx 还有 D:\Desktop 越级失效路径 |
| eval `make_golden_queries`/`compare_reports`/`clause_calibrate`/`build_citation_review_sheet` | 手动工具，不在回归链，产物已 gitignore |

### 死代码片段（函数级，第5步随重构清）
- `changelog.py`: `log_file_change`/`log_kb_status`/`read_log` 三函数零调用
- `standard_status.py`: `build_records_from_manifest` 零调用
- `verify.py`: `check_citation_accuracy` 仅 self-test 用，未进主管线 + ai_hint 入参类型错
- `date_shift.py`: `replacer`/首个 `expand_short` 定义后从未调用

### 死配置 key（kb.json，第5步清）
- `paths.kb_images`(orchestrator 用硬编码字符串，不读此 key)
- `search.min_similarity`(无代码读 cfg)
- `pipeline.{min_standards_threshold,max_extract_retries,max_index_build_timeout}`(整个 pipeline 顶层块零消费)

## 四、改（失效/重叠，留给框架改造第5步）

| 项 | 处理方向 |
|---|---|
| B1–B5 五个潜伏 bug | 见第二节 |
| `kb_param_extract.py` | 产物 `kb_param_index.json` 在线被 resolver+server 消费，却游离自动链路 → 纳入 C1 自动重建 |
| `verify.py` ∩ `scan.py` 数值冲突检测 | 三键正则两处重复 → 合并去重 |
| `kb_corrector.py` ∩ `kb_enhancer.py` | 职责重叠且 corrector 未进主管线 → 合并，corrector 降为 enhancer 一模式 |
| F2 数据/代码混杂 | 运行态产物统一迁 data/，写死路径改走 kb.json |

## 五、留（健康，构成系统骨架）

- **检索核心**：`kb.py`(访问层)、`kb.json`(配置源)、`server.py`、`kb_resolver_core.py`(门面)、`kb_ppr_engine.py` + resolver 子包(_common + 8 mixin)。**resolver 拆分经核实干净：无环、8 mixin 继承完整、`__all__` 导出完备**。
- **建库链路(14)**：orchestrator 经 subprocess 串起的 A→D 主流程脚本。
- **在线依赖**：`kb_vector_search_local`(向量后端)、`clause_vector_search`、`support_guard`、`standard_status`、`metrics`、`changelog.record`。
- **运维 CLI**：`kb_self_test`/`kb_current_state`/`kb_rollback`/`kb_feedback_processor`/`kb_feedback_report`。
- **plan_writer 主链路(9)**：orchestrator/content_generator/render_engine/kb_auditor/retrieval_core/verify/scan/kb_enhancer + 工具基座(_utils/_docx_notes/llm_hint)。
- **外部入口**：`kb_loader.py`(Codex 4-API 适配器)、`plan_bridge.py`(build_plan/plan_status，注：无 build_plan_com)。
- **安全网+契约**：3 张回归/特征化网 + kb_eval/kb_truth_eval/clause_eval/plan_writer_citation_eval；schemas(纯文档契约)、project_type_map(活跃)。

## 六、依赖拓扑结论（框架设计输入）

`pipeline → kb_core`、`plan_writer → kb_core`、`kb_core → resolver(内部)`，**单向收敛到 kb_core 访问层，无环**。隐式分层已成型(建库/检索/消费/外部适配/评测)。**拓扑本身健康，不需重塑**——框架改造的真正工作是：①把数据产物请出代码目录(F2)、②显式化 contracts 层(F3)、③定 PPR 去留(F1)、④清掉 B1–B5 静默失效。

---
*生成：第1步全面普筛 · 4 子代理并行 + 主控核实 · 安全网基线 kb_self_test 19/20、verify self-test 8/9(既存无关 FAIL)*
