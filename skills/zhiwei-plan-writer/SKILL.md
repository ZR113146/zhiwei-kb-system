---
name: zhiwei-plan-writer
description: >
  知微施工方案编制与 Word 输出应用层。基于 zhiwei-kb 规范事实层,经统一 retrieval_core 复用检索;
  支持方案生成、章节推荐、引用审计(四问对照)、无引用技术段落发现、KB 增强、条款修正、
  python-docx 渲染导出、项目隔离与 citation audit 回归。
---

# 知微方案编制(应用层)

## 定位与边界

`zhiwei-plan-writer` 是施工方案应用层,**不维护第二套知识库事实逻辑**——经 `kb_loader.py` 与
`plan_writer/retrieval_core.py` 复用 `zhiwei-kb` 的检索/条款/名称解析能力。
规范事实、时效状态、条款读取、召回排序属 `zhiwei-kb`;方案章节、引用审计、文档增强修正、Word 输出属本技能。
此边界镜像代码库 `plan_writer → kb_core` 单向依赖,勿绕过 retrieval_core 重实现检索事实逻辑。

## 入口

- 项目根:`D:/zhiwei-kb-system`;上游技能:`zhiwei-kb`
- 接入口:`plan_bridge.py`(`build_plan` / `plan_status`)
- 构建器:`plan_writer/`
- 统一检索适配层:`plan_writer/retrieval_core.py`
- 引用审计入口:`plan_writer/kb_auditor.py`
- 路径真相源:`kb_core/kb.json`;审计台账:`docs/tasks/CURRENT_STATE_INDEX.md`

## 公开能力

- `build_plan(project_dir, output_dir=None, append_citation_summary=False)`:批量生成方案 `.docx`(python-docx)。
- `plan_status()`:检查编排器 / KB / pipeline / plan_writer 可用性。
- `audit_report(docx_path)`:引用审计四问对照表 + 结构化 entries。
- `citation_audit_summary(entries)` / `write_citation_audit_summary()` / `append_citation_audit_summary_to_docx()`:汇总与输出。
- `resolve_for_chapter(chapter, topic)` / `suggest_citations(docx_path)`:章节推荐 / 无引用技术段落发现。

> Word COM 输出路径(build_plan_com 等)已整体移除,统一 python-docx 渲染。

## 三条管线

- **生成渲染**:`content_generator.py → build.py` → `ch01~ch09` + `project.json` + `standards_guide.json` + `.docx`。
- **审计核验**:`scan.py → verify.py → kb_auditor.py` → 结构 / 占位符 / 规范版本 / 条款引用 / AI·Web 断言。
- **增强修正**:`kb_enhancer.py → kb_corrector.py` → 发现可补引用技术段落,写入 KB 引用或修正注记。

结构约定:`_yellow_append` 已收口到 `plan_writer/_docx_notes.py`(yellow_append / paragraph_by_index),
enhancer 与 corrector 共用;orchestrator 单次审计(不产生冗余二次 audit / 双批注)。

## kb_auditor 关键 helper(勿堆回主函数)

- `_resolve_citation`:三阶段 citation 验证主入口。
- `_load_clause_full` / `_attach_clause_audit`:复用 KB 完整条款 + 审计元数据。
- `_value_exists_in_kb` / `_same_standard_matches` / `_anchor_enhanced_matches`:宽/窄/锚点增强验证。
- `_set_citation_suggestion` · `_parse_clause_reference` / `_retry_citation_with_ai_hint` / `_render_audit_entry_lines`。
- 结构化摘要 / Word 表格输出 helper 组。

## 检索复用(retrieval_core)

- `chapter_recommend`:章节/专题规范与条款候选,服务生成管线。
- `long_context_search`:长文本段落检索,服务 verify.py 的 AI/Web 断言核验。
- `citation_discovery`:发现无引用技术段落,服务 kb_auditor / kb_enhancer。
- 复用 `zhiwei-kb` 的四通道召回(direct/lexical/semantic/structure,现均叶子条款粒度)——
  条款级引用验证因此更精确。不要绕过 retrieval_core 或 zhiwei-kb 另起搜索逻辑。

## 工作流

1. 先用 `zhiwei-kb` 确认关键规范与条文依据。
2. 组织 `content/` 或 `projects/<name>/content/` 隔离项目。
3. `content_generator.py` 生成 `ch01~ch09` + 规范指南。
4. `build_plan()` 或 `build.py` 输出 `.docx`。
5. 依次 scan → verify → audit,按需 enhance → correct。
6. 深改前读 `docs/tasks/CURRENT_STATE_INDEX.md` + 项目 ADR 记忆。

## 验证命令

```powershell
python -m py_compile plan_writer\kb_auditor.py kb_core\kb_resolver_core.py

# 引用审计专项回归(最近 4/4 通过)
python eval\plan_writer_citation_eval.py
```

已知状态:
- `python plan_writer\verify.py --self-test` 有既有失败 `check_code_names: version_rename detected`——
  非 citation 回归,勿误判;同 self-test 的 `citation_accuracy: L2 fallback` 通过。
- 验证会改写 eval 报告时间戳 / 样例 docx。运行期日志(`kb_core/.changelog.jsonl` 等)已 gitignore;
  受版本控制的 `eval/plan_writer_citation_eval_report.*` 与 `eval/plan_writer_citation_sample*.docx`
  若只是验证副作用应还原。
- 控制台 gbk:含 `✓` 输出用 `PYTHONIOENCODING=utf-8`;需语义召回时先设 `SILICONFLOW_API_KEY`。

## 运行约束

- 方案生成只经 `kb_loader.py` 与 `retrieval_core` 间接访问知识库;`kb_core/kb.json` 是路径真相源,不硬编码。
- 保留现有章节结构、深度与质量基线;不把 Obsidian 前端职责写回工具层。
- 修正器不得以固定段落号为唯一定位,旧规则只作兼容降级。
- 结构优化不改公开参数/输出字段/suggestion 文案/异常吞吐/文件输出格式,除非用户明确要求行为变更。
- 规范事实、条款读取、召回排序交给 `zhiwei-kb`。
