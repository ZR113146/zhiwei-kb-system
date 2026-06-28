# 知微 KB 系统 — 目标框架设计（待评审冻结）

> 第 3 步产物。基于第 1 步普筛裁决表（AUDIT.md）+ 三轮 PPR 消融 + 依赖拓扑实证。
> **本文档需用户评审冻结后，才进第 4 步（蚂蚁搬家）。** 冻结前任何条目都可改。
> 设计基调：**保守解耦不改名 + 参数化边界 + 暂不预留多库**（用证据约束改动，只解决被证明存在的问题）。

---

## 一、设计原则（约束所有后续决策）

1. **只解决实证存在的问题**：F2（数据/代码混杂）、F3（缺 contracts 层）、写死路径、5 个潜伏 bug、PPR 退役。不为命名美学或假想需求改动。
2. **保留顶层目录名**：`kb_core` / `pipeline` / `plan_writer` 已按职责分清，是健康的隐式分层。改名要动几乎所有 import，而 pipeline/plan_writer 是安全网盲区——高风险零收益。**显式化已有分层，不推倒重来**。
3. **依赖单向、无环**（已实证）：`pipeline → kb_core`、`plan_writer → kb_core`、`kb_core → resolver(内部)`。新框架必须维持这个方向，**任何引入反向/环形依赖的改动一律否决**。
4. **参数化边界，不硬编码单库**：检索层接收"库的路径/配置"作为参数，不写死 `data/kb_json`。为未来多库留余地，但不建多库脚手架（YAGNI）。
5. **行为保持**：第 4 步纯搬迁（行为不变、快照守护），第 5 步才改逻辑。设计本身不改变任何运行时行为。
6. **跨平台可移植**（用户需求：Claude Code + Codex 双平台运行）：消除"靠当前目录/用户名硬假设"的脆弱点。具体——① 收敛 37 处 `sys.path.insert` 为单一引导或包内相对导入；② 一切文件寻址走 contracts/kb.json，不靠"脚本在哪"；③ 清除 `USERNAME` 默认值 `'zhaor'` 等个人环境残留；④ API key 等平台差异项走环境变量 + 文档说明，不写死。**底子已好**（路径用 expanduser、无硬编码 `D:\`），主要债务是 sys.path 散落。

---

## 二、目标分层（5 层 + 1 归档区）

```
zhiwei-kb-system/
├─ contracts/      【新增】契约层 — 源数据 + schema + 配置，所有层的单一真相源
├─ kb_core/        检索核心（含 resolver/ 子包）+ HTTP 服务
├─ pipeline/       离线建库流水线（产出 → data/）
├─ plan_writer/    下游消费：施工方案生成
├─ eval/           评估脚本 + golden 输入 + 回归基线
├─ data/           运行时产物（gitignore，pipeline 重建）
├─ scripts/        运维 .bat/.ps1
└─ archive/        已归档的死/实验代码（不参与运行）
```

### 各层职责与依赖规则

| 层 | 职责 | 允许依赖 | 禁止 |
|---|---|---|---|
| **contracts/** | 持有源数据(`kb_term_map*`/`standard_tags`)、schema、`kb.json` 配置。**无逻辑、纯数据/契约** | 无（最底层） | 不依赖任何代码层 |
| **kb_core/** | 检索核心：访问层(KB)、resolver 子包、PPR-退役后的 legacy+向量检索、HTTP 服务 | contracts、data(只读产物) | 不依赖 pipeline/plan_writer/eval |
| **pipeline/** | 离线建库：A→D 相位调度，产出索引到 data/ | contracts、kb_core(访问层) | 不依赖 plan_writer |
| **plan_writer/** | 消费检索结果生成 Word 方案 | contracts、kb_core(访问层) | 不依赖 pipeline 内部 |
| **eval/** | 回归/特征化网 + 评测 | contracts、kb_core、pipeline、plan_writer | 不被任何运行代码依赖 |
| **data/** | 运行时产物（索引/向量/MD库/运行态日志） | — | gitignore，不入版本库 |

**核心规则**：上层可依赖下层的**公开访问层**(KB 类 / kb_loader)，不得 reach into 下层内部模块。contracts 是所有层的共同底座，本身零依赖。

---

## 三、contracts/ 层定义（F3 的解）

把散落的源数据/契约集中，**让"数据格式即契约"显式可见**：

```
contracts/
├─ kb.json                 (从 kb_core/ 移入 — 路径配置真相源)
├─ term_map.json           (从 pipeline/kb_term_map.json 移入)
├─ term_map_v3.json        (从 pipeline/kb_term_map_v3.json 移入)
├─ standard_tags.json      (从 plan_writer/ 移入)
├─ project_type_map.json   (从 plan_writer/ 移入)
└─ schemas/                (从 schemas/ 移入 — citation/standard_status)
```

**判据**：进 contracts 的是 ①不可重建的源数据 或 ②跨层共享的契约/配置。**可重建的产物不进 contracts，进 data/**。

**风险标注**：这些文件被代码写死路径引用（B5 的 kb_auditor、6 处 term_map、3 处 standard_tags）。移动**必须**配合改路径——这是第 5 步的工作，**不在第 4 步搬迁范围**（第 4 步只搬无路径耦合的）。contracts 层的物理建立，因此跨第 4/5 步：先建目录+移可安全移的，写死路径的随第 5 步改引用一起归位。

---

## 四、data/ 归位方案（F2 的解）

**问题**：~12 个 pipeline 脚本用 `os.path.dirname(__file__)` 把运行态产物写进代码目录（`kb_search_log.jsonl`/`kb_tag_scores.json`/`batch_failed.json`/`kb_*_suggestions.json` 等）。

**方案**：新增 `data/pipeline_state/`，所有运行态产物迁入；脚本路径常量从写死 `__file__` 改为从 `kb.json` 读。

**判据三分法**：
- **运行态产物**（日志/中间状态/可重建）→ `data/`，gitignore
- **源数据/契约**（不可重建/手维护）→ `contracts/`，入库
- **配置**（kb.json）→ `contracts/`，入库

**注意**：这批是**写死路径改写**，属第 5 步（有逻辑改动+需安全网）。第 4 步不碰。

---

## 五、PPR 退役在框架中的落位（F1 已决策）

- 检索层简化为 **legacy 关键词 + 向量语义**，NL 分支去掉 PPR 融合。
- `kb_ppr_engine` + 4 个配套脚本 → `archive/`（先断 `_run_nl_branch`/`kb_quality` 引用，第 5 步）。
- `data/kb_json/kb_ppr_graph.json`(12MB) + 相关产物删除。
- kb.json 的 `kb_ppr_graph`/`kb_phrase_model`/`kb_word_vectors`/`kb_word_vocab` 配置 key 清理。
- **多库红利**：退役 PPR 单一巨图后，向量索引可按库独立，天然支持未来多库隔离——这是"参数化边界"得以成立的前提。

---

## 六、参数化边界（多库预留的唯一动作）

**不建多库脚手架，只守一条规则**：检索层（kb_core）接收"库配置"作为参数/配置项，不在代码里硬编码 `data/kb_json` 等单库路径。

- 现状：路径已大部分走 `kb.json`（`_load_paths`），方向正确。
- 设计要求：第 5 步治理写死路径时，确保新增/改写的路径**全部经 kb.json**，不留新的硬编码。
- 未来加库 = 加一份库配置，不改检索层代码。**现在不实现多库逻辑**。

---

## 七、执行边界（第 4 步 vs 第 5 步，防止越界）

| 动作 | 步骤 | 安全网 |
|---|---|---|
| 建 contracts/ 目录、移**无路径耦合**的契约文件 | 第4步 | 快照 |
| schemas/ 移入 contracts/（零代码加载，纯文档） | 第4步 | 无需（无引用） |
| 写死路径文件（term_map/standard_tags/kb.json）移入 + 改引用 | **第5步** | 快照+集成 |
| data/pipeline_state/ 归位 + 脚本路径改写 | **第5步** | 需补 pipeline 特征化测试 |
| PPR 退役（断引用+归档+删产物+清配置） | **第5步** | 快照（确认 NL 召回不退） |
| 5 个潜伏 bug 修复 | **第5步** | 对应特征化测试 |
| 死配置 key / 死函数清理 | **第5步** | 快照 |

**关键约束**：第 4 步只做"零行为风险的纯搬迁"，凡涉及改 import/路径/逻辑的，一律第 5 步 + 安全网。

---

## 八、评审决议（已冻结 2026-06-28）

1. **契约层命名 = `contracts/`** —— 分层架构标准术语，专指各层共同依赖的稳定约定层，覆盖本层内容（kb.json 配置 + term_map/standard_tags 源数据映射 + schema 契约）。
2. **schemas 移入保留，不接 jsonschema 校验** —— 校验是新功能，本次是重构非加功能，不混入。
3. **archive/ 保持入库** —— 留追溯；以后若要彻底移出再 gitignore。
4. **第 4/5 步边界认可** —— 第 4 步只搬无路径耦合的，第 5 步才动写死路径/逻辑。

**状态：本货架图（目录分层）已冻结。** 下一步补 `CODEMAP.md`（代码/工具层接线改造方案，函数级），两份都冻结后才进第 4 步。

---
*第 3a 步框架货架图 · 已冻结 · 基于 AUDIT.md 裁决表 + 三轮 PPR 消融 + 依赖拓扑实证*
