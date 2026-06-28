# 知微 KB 系统 — 代码/工具层接线改造方案 (CODEMAP)

> 第 3b 步产物。FRAMEWORK.md 是"货架图"(东西放哪)，本文档是"接线图"(模块内部怎么连、怎么改)。
> **需评审冻结后才进第 4/5 步。** 每个改造点标注：现状 → 目标 → 依赖顺序 → 安全网 → 落在第几步。
> 目标对齐用户四要求：**高效调用 / 逻辑清晰 / 体量精简 / 不造轮子**，外加**跨平台(Claude Code + Codex)**。

---

## 一、改造目的（一句话）

拓扑本身健康（单向收敛 kb_core、无环），问题不在"谁依赖谁"，而在**接线方式脆弱**：基础设施函数被抄多份、文件路径写死、导入靠 37 处 sys.path hack。改造目的 = **让连接变稳、变少、可跨平台**，不动健康的依赖方向。

---

## 二、改造点清单（按主题分组）

### A. 消除造轮子 — 基础设施函数收归单一正主【不造轮子 + 逻辑清晰】

| 改造点 | 现状 | 目标 | 安全网 |
|---|---|---|---|
| A1 `_load_paths` ×3 | `_common.py`/`clause_vector_search.py`/`kb_ppr_engine.py` 各自重解析 kb.json | 统一用 `kb.py: load_config()` 为唯一正主（或提到 contracts 的 config 加载器），三处改 import | 快照+集成 |
| A2 `normalize_code` ×2 | `_common.py` + `standard_status.py` 两份 | 定一个正主（standard_status 更底层），另一处 import | 快照（编码归一化是检索关键路径） |
| A3 `extract_code` ×3 | `_common`/`kb_ppr_graph`/`pipeline_orchestrator` | 正主留 `_common`/contracts，其余 import；kb_ppr_graph 保留(PPR 保留)，按需 import | 快照 |
| A4 `extract_code_from_result` ×3 | eval 三脚本各写一遍 | 合并到一个 eval 共享工具模块 | eval 自测 |
| A5 `_load`/`_load_jsonl` ×6 | 散落自写 JSON 加载 | 收归 contracts 一个轻量 io 工具（仅标准库 json 包装，不引依赖） | 对应脚本 |

> 注：A 组是"合并"不是"删除"——把抄多份的收成一份、各处 import。这直接回应"别重复造轮子"。

### B. 路径治理 — 写死路径全改走 contracts/kb.json【高效调用 + 跨平台】

| 改造点 | 现状 | 目标 | 安全网 |
|---|---|---|---|
| B1 term_map 写死 ×6 | 6 处 `os.path.dirname(__file__)/kb_term_map.json` | 全改走 `load_config()['paths']['kb_term_map']`，文件移 contracts/ | 快照+集成（jieba 术语加载） |
| B2 standard_tags 写死 ×3 | kb.py/content_generator/scan 各拼同目录 | 走 kb.json 配置，文件移 contracts/ | verify self-test |
| B3 B5-bug kb_auditor 失效路径 | 指向不存在的 `pipeline/scripts/` | 修正为 contracts 路径（顺带修复静默失效的 jieba 加载） | 补 kb_auditor 锚点测试 |
| B4 data/pipeline_state 归位 | ~12 脚本用 __file__ 写运行态 JSON 进代码目录 | 新建 `data/pipeline_state/`，路径走 kb.json | 需先补 pipeline 特征化测试 |

### C. 跨平台可移植【Claude Code + Codex 双平台】

| 改造点 | 现状 | 目标 | 安全网 |
|---|---|---|---|
| C1 `sys.path.insert` ×37 | 每脚本手动注入路径 | 收敛为单一引导点（如各目录 `__init__.py` + 一处 path 设置）或包内相对导入 | 全套安全网（影响所有导入） |
| C2 `USERNAME` 默认 `'zhaor'` | 个人用户名写死兜底 | 改为平台无关的兜底（空或 `'unknown'`） | 对应脚本 |
| C3 API key 环境变量 | SILICONFLOW/ANTHROPIC_API_KEY | 保持环境变量 + 在 README/环境变量.example 文档化双平台配置 | 无需（已是环境变量） |

> C1 是最大的可移植性债务，也是风险最高的改造（影响所有导入）。**建议单独成一个子阶段、最后做、全套安全网兜底**。

### D. PPR 保留 + 修复加固【F1 翻转：消融纠错后证 PPR 有 ~3 点召回贡献，保留】

| 改造点 | 现状 | 目标 | 安全网 |
|---|---|---|---|
| D1 修图重建 | orchestrator 不再重建 kb_ppr_graph，用 17 天旧图 | orchestrator 自动重建 kb_ppr_graph（新规范纳入 PPR 路径） | 集成（kb_self_test）+ 图特征化 |
| D2 解决线程非确定性 | ThreadPool(legacy∥ppr) as_completed 顺序致 ppr+legacy ~16% 跨进程漂移 | 固定合并顺序/串行化，使分支确定 | snapshot（确认 recall 不退 + 漂移消除） |
| D3 PPR 簇去留 | engine/graph 活跃；grid_search/quality/term_bge_augment 疑一次性 | engine/graph **保留**；后三者单独评估是否归档 | — |
| ~~删图/清配置~~ | — | **取消**（保留 PPR，图与配置 key 都要留） | — |

### E. 死代码/死配置清理【体量精简】

| 改造点 | 内容 | 安全网 |
|---|---|---|
| E1 死配置 key | kb.json: `search.min_similarity`、`pipeline.*` 整块、`paths.kb_images` | 集成 |
| E2 死函数 | changelog 3 函数 / standard_status.build_records_from_manifest / verify.check_citation_accuracy | 快照 |
| E3 潜伏 bug B1/B2 | staticmethod 错绑 + _rewrite_head_scores 缺 self | 补 clause_rerank + index-rebuild 测试 |
| E4 bug B4 | orchestrator 调缺失的 kb_watch_vectors.py | 补回或删除该 subprocess 步 |
| E5 重叠合并 | verify∩scan 数值冲突检测 / kb_corrector∩kb_enhancer | 对应自测 |

---

## 三、依赖顺序（哪些必须先做，防止边改边断）

```
前置: 建 contracts/ 目录 (第4步搬无耦合的 schemas)
  ↓
阶段1 (低风险, 先做): A 组函数合并 + E1/E2 死物清理
  ↓
阶段2: B 组路径治理 (依赖 contracts/ 已建好) + B3 修 bug
  ↓
阶段3: D 组 PPR 修复加固 (独立, 可与阶段1/2 并行)
  ↓
阶段4 (最高风险, 最后做): C1 sys.path 收敛 (影响所有导入, 全套安全网)
  ↓
收尾: E3/E4/E5 剩余 bug 与重叠合并
```

**铁律**：每阶段做完跑全套安全网（snapshot + kb_self_test + verify self-test），绿了才进下一阶段。C1 因影响面最大，单独成阶段、放最后。

---

## 四、安全网缺口（动手前必须补）

| 盲区 | 涉及改造点 | 需补 |
|---|---|---|
| pipeline 30+ 脚本 | B4 数据归位、D PPR 修图重建 | 关键脚本特征化测试（像 build_graph/extract_headings 那样） |
| plan_writer 渲染/编排 | B2/E5 | content_generator/render 的输出特征化 |
| kb_auditor 锚点提取 | B3 | jieba 术语加载的断言（修复 B5 后才有意义） |

**原则**：动某区域前先补该区域的特征化测试（第 0 步原则贯穿）。无网区域不动。

---

## 五、预期收益（量化）

- **体量**：死函数/死配置清理（PPR 簇已决保留，不再计入精简）。
- **造轮子**：`_load_paths` 3→1、`normalize_code` 2→1、`extract_code` 3→1、JSON 加载 6→1。
- **跨平台**：37 处 sys.path → 单一引导；清除个人环境残留。
- **可信**：5 个潜伏 bug 修复（含静默失效的 clause_rerank）。
- **高效调用**：写死路径全走 kb.json，文件可自由移动不断线。

---

## 六、评审决议（已冻结 2026-06-28）

1. **C1 = 方案甲：做成可 `pip install -e .` 的标准包**（加 pyproject.toml）。一次性消灭 37 处 sys.path.insert，Claude Code + Codex 双平台都能 `import kb_core` 直接用。改动面大但治本，放阶段4最后做、全套安全网兜底。
2. **阶段化认可**：低风险(A/E)先行 → B 路径治理 → D PPR 修复加固(可并行) → C1 打包(最后) → 收尾。
3. **先补网再改认可**：动 pipeline/plan_writer 盲区前先补特征化测试。
4. 改造点清单认可。

**状态：接线图已冻结。** FRAMEWORK(货架) + CODEMAP(接线) 双冻结，可进第 4 步。

---
*第 3b 步代码接线图 · 已冻结 · 基于代码图实证(造轮子/路径/sys.path 统计) + AUDIT.md*
