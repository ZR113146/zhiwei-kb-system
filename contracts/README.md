# contracts/ — 契约层

各代码层共同依赖的**稳定约定层**：源数据映射、JSON Schema 契约、配置。**无逻辑、纯数据/契约。**

依赖规则：本层不依赖任何代码层；`kb_core` / `pipeline` / `plan_writer` / `eval` 均可依赖本层。

## 当前内容

| 文件 | 角色 | 加载方 |
|---|---|---|
| `citation.schema.json` | 引用对象 JSON Schema（纯文档契约，当前零代码加载） | 文档参考 |
| `standard_status.schema.json` | 版本状态 JSON Schema（同上） | 文档参考 |

## 规划迁入（第 5 步，需配合改写死路径）

按 FRAMEWORK.md / CODEMAP.md 冻结方案，以下源数据/配置将在第 5 步迁入本层（迁移同时把代码里 `os.path.dirname(__file__)` 写死路径改为经 `kb.json` 寻址）：

- `kb.json`（路径配置真相源，现在 kb_core/）
- `term_map.json` / `term_map_v3.json`（现在 pipeline/，6 处写死引用）
- `standard_tags.json` / `project_type_map.json`（现在 plan_writer/，3 处写死引用）

判据：**不可重建的源数据 / 跨层共享的契约配置** → 进 contracts/；可重建产物 → 进 data/。
