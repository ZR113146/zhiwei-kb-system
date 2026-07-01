# zhiwei-kb-system

本地建筑规范垂直知识库 —— 规范检索事实层 + 施工方案编制应用层。

面向工程建设标准(GB/JGJ/CJJ/CECS/DB 等),把 PDF 规范解析入库,提供
**标准/条款级高精度召回**,并据此**自动编制施工方案 Word 文档**并做引用审计。

- Python `>=3.10` · 包名 `zhiwei-kb` v9 · `pip install -e .`
- 检索地基指标:条款定位 `Clause@3` 0.2 → **0.85**

---

## 能力

**检索(事实层 `kb_core`)**
- 标准编号 / 名称 / 条文号直查,自然语言技术问题、长文本查询
- 四通道召回:精确直查 + 词面 BM25 + 语义向量 + 图传播(均**叶子条款粒度**)
- 条款正文读取、时效状态(现行/废止/被替代)、引用支撑判定、图片上下文、反馈记录

**方案编制(应用层 `plan_writer`)**
- 批量生成施工方案 `.docx`(python-docx)
- 章节推荐、引用审计(四问对照)、无引用技术段落发现、KB 增强与条款修正

---

## 架构(分层 + 单向依赖)

```
接入层    server.py (FastAPI /api/*)  ·  kb_loader.py(检索门面)
   │
事实层    kb_core/   KBResolver = 分支路由 + 6 Mixin
   │        code_norm(码归一化唯一真源) · standard_status · support_guard
   │        clause_vector_search · kb_ppr_engine(格PPR)
   ▲(单向)
应用层    plan_writer/  经 retrieval_core 复用事实层, 不重实现检索逻辑
   │
构建层    pipeline/  (pipeline_orchestrator 调度离线入库+建索引)
   │
数据/契约 data/index(MD本体) · data/kb_json(索引产物, gitignore) · contracts/(schema)
```

> 详见 `FRAMEWORK.md`(货架图)、`CODEMAP.md`(接线)、`AUDIT.md`(审计结论)、
> 桌面《zhiwei项目框架流程图》。

### 召回四通道(设计核心)

| 通道 | 索引 | 机制 |
|---|---|---|
| direct 直查 | `kb_clause_index.json` | `标准码:条款号` 精确查找,normative 优先 |
| lexical 词面 | `kb_body_bm25.json` | 段级 BM25 |
| semantic 语义 | `kb_sentence_vectors.faiss` | BGE-M3 cosine,条款级精定位 |
| structure 结构 | `kb_ppr_graph.json` | 格PPR 分词 → 图传播 → 交替强化 |

NL 查询:PPR + legacy 并行 → 晚融合 → 句向量精排 → 可选 LLM 重排 → 支撑判定。

---

## 快速开始

```bash
pip install -e .            # 安装 kb_core 包 + 依赖
```

配置两个 API key(检索的可选增强,方案编制/语义召回需要):

```powershell
# 语义嵌入(BGE-M3)
[Environment]::SetEnvironmentVariable('SILICONFLOW_API_KEY','<你的SiliconFlow密钥>','User')
# LLM 重排(DeepSeek 端点)
[Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY','<你的DeepSeek密钥>','User')
```

> 未设 `SILICONFLOW_API_KEY` 时语义通道**静默降级**(词面+直查+图仍可用),非报错。

检索:

```python
from kb_core.kb import KB
kb = KB()
kb.search('临时消防给水 1000m2', max_results=5)   # 四通道混合召回
kb.read_clause_full('GBT50720', '5.3.4')          # 条款正文 + 时效 + 审计元数据
kb.status()                                        # 索引/条款/向量健康
```

方案编制:

```python
import plan_bridge
plan_bridge.build_plan('projects/<name>')          # 生成 .docx
plan_bridge.plan_status()
```

---

## 索引构建管线

`pipeline_orchestrator.py` 调度(PDF → MD → 索引):

```
Phase A 命名校验+去重+切割 → Phase B MinerU 解析 → Phase C 建索引链:
  kb_search_index(分段基座:# 标题 + 叶子条款 X.Y.Z)
   → kb_term_index → kb_build_phrase_model → kb_body_bm25
   → kb_ppr_graph → kb_clause_index → cross_refs / image_index
   → [--embed-clauses] kb_sentence_vectors(付费 BGE-M3, opt-in + key 门控)
→ Phase D 完整性+端到端校验
```

- 改分段基座后**按链重建**;守护用**聚合召回指纹**(recall@5/mrr/ndcg),带 `PYTHONHASHSEED=0`。
- `data/kb_json/*` 索引产物为 gitignore 构建产物,克隆后需重建。

---

## 项目结构

```
kb_core/       检索内核(KBResolver + resolver/ mixins + code_norm/standard_status/support_guard)
pipeline/      入库与建索引器 + orchestrator
plan_writer/   方案生成/审计/增强/渲染
contracts/     schema + 术语映射(路径经 kb_core/kb.json 治理)
eval/          回归守护(snapshot_regression / code_norm_consistency / kb_truth_eval / 引用审计)
data/          index(MD本体) + kb_json(索引产物, gitignore)
docs/          审计台账 docs/tasks/CURRENT_STATE_INDEX.md
kb_loader.py   检索门面 · plan_bridge.py 方案入口 · server.py FastAPI
```

---

## 评测与守护

```powershell
$env:PYTHONHASHSEED="0"; $env:PYTHONIOENCODING="utf-8"
python eval\code_norm_consistency.py       # 归一化多入口一致性(防碎片化)
python eval\snapshot_regression.py         # 检索主干聚合召回指纹
python pipeline\kb_search_quality.py --check   # 质量门(退化 exit 1)
python eval\kb_truth_eval.py               # 真值评测(需两 key)
python eval\plan_writer_citation_eval.py   # 引用审计回归
```

---

## 约束

- **`kb_core/kb.json` 是路径唯一真相源**,不硬编码替代路径。
- **`code_norm.py` 是标准码归一化唯一真源**,所有入口委托它,勿各写正则。
- 不编辑 `data/index/` 知识库正文本体(除非明确数据修复)。
- 优化不改公开参数/返回字段/排序策略,除非明确要求行为变更;一次一改、跑守护比基线、退化即回退。

---

## 外部依赖

MinerU(PDF→MD 解析)· SiliconFlow BGE-M3(嵌入)· DeepSeek(LLM 重排)·
jieba · faiss-cpu · scipy · numpy · FastAPI · python-docx
