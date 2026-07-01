# skills/

本目录是两个 AI 技能的**权威源**(单一真相源),随代码在同一 PR 内审查/更新,避免漂移。

- `zhiwei-kb/SKILL.md` —— 规范检索事实层(kb_core)
- `zhiwei-plan-writer/SKILL.md` —— 施工方案编制应用层(plan_writer)

## 部署(副本,从此处同步)

平台实际加载位置(把此处内容复制过去即可):

```powershell
# Codex
Copy-Item skills\zhiwei-kb\SKILL.md        $HOME\.codex\skills\zhiwei-kb\SKILL.md
Copy-Item skills\zhiwei-plan-writer\SKILL.md $HOME\.codex\skills\zhiwei-plan-writer\SKILL.md
# Claude
Copy-Item skills\zhiwei-kb\SKILL.md        $HOME\.claude\skills\zhiwei-kb\SKILL.md
Copy-Item skills\zhiwei-plan-writer\SKILL.md $HOME\.claude\skills\zhiwei-plan-writer\SKILL.md
```

Codex 平台绑定 `agents/openai.yaml` 是平台专属配置,不纳入本仓库;
Claude 直接从 SKILL.md frontmatter 发现技能,无需额外文件。

## 维护约束

改动 kb_core/pipeline/plan_writer 的架构、归一化真源、召回通道、公开 API 或验证命令时,
**同步更新对应 SKILL.md**,否则技能会像旧版一样引用已废内部(如 `_CODE_PREFIX_ALT`、
`__verify_chain`)误导使用者。
