---
name: zhiwei-kb
description: >
  知微建筑规范知识库的检索事实层:标准编号/名称/条文号查询、条款正文读取、时效状态、
  语义/词面/图传播/直查四通道召回、图片上下文、反馈记录、代码图谱审计与索引重建。
  作为 zhiwei-plan-writer 的规范事实层。适用于标准检索、条款定位、召回质量调优、
  索引管线维护、归一化一致性守护。
---

# 知微 KB(规范事实层)

## 定位与边界

`zhiwei-kb` 只负责**规范事实**:知识库检索、条款读取、时效状态、图片上下文、反馈记录、
索引管线维护。方案编制、引用审计、增强修正、Word 输出属于 `zhiwei-plan-writer`。
两技能的边界镜像代码库的 `kb_core`(事实层)↔ `plan_writer`(应用层)单向依赖,勿越界。

## 入口

- 项目根:`D:/zhiwei-kb-system`(已 `pip install -e .`,包名 zhiwei-kb v9,packages=kb_core, kb_core.resolver)
- **路径真相源**:`kb_core/kb.json`(paths + api 块);只经它解析路径,不硬编码
- 检索门面:`kb_loader.py`(search / search_with_support / read_clause / read_clause_full / status / search_vector / feedback)
- 检索内核:`kb_core/kb.py`(KB 类)→ `kb_core/kb_resolver_core.py`(KBResolver)
- 代码图谱:semantic-memory MCP,项目名 **`D-zhiwei-kb-system`**(本地工件 `.semantic-memory/artifact.json`)

## 架构:KBResolver = 分支路由 + 6 Mixin

`KBResolver` 已拆为分支路由 + Mixin 组合(勿把逻辑堆回长函数):
QueryClassifier(分类/直查解析)· ClauseRead(条款定位/正文)· Ranking · PprFusion(PPR+legacy 晚融合)·
ClauseRefine(句向量精排 + LLM 重排)· Confidence。

底层能力:`code_norm`(码归一化唯一真源)· `standard_status`(时效)· `support_guard`(支撑判定)·
`clause_vector_search`(语义)· `kb_ppr_engine`(格PPR+图传播)。

## 召回四通道(设计核心,均已叶子条款粒度)

| 通道 | 索引 | 机制 |
|---|---|---|
| direct 直查 | kb_clause_index.json | `std:number` 精确查找,**normative 优先**(不被条文说明覆盖) |
| lexical 词面 | kb_body_bm25.json | 段级 BM25(k1/b) |
| semantic 语义 | kb_sentence_vectors.faiss + meta | BGE-M3 cosine,条款级精定位/重排 |
| structure 结构 | kb_ppr_graph.json | 格PPR 分词 → 种子 → CSR 稀疏传播(α=0.85) → 交替强化 |

NL 查询:Stage1 PPR+legacy 并行 → `_merge_nl_candidates` 晚融合(权重 search_tuning 可调)→
clause_rerank 句向量精定位 → 可选 DeepSeek LLM 重排 → support_guard 判定。

## 归一化唯一真源(最重要的约束)

- **`kb_core/code_norm.py` 是标准码归一化的唯一真源**(零依赖:normalize_code / extract_standard / official_code)。
  standard_status 等经 re-export 兼容;所有入口(pipeline 抽取器/resolver/status)一律委托它。
- 标准码多形态(`GB/T`·`GB_T`·`GBT`·带年份·全角),匹配一律**去分隔符子串包含**,勿用正则前缀。
- `eval/code_norm_consistency.py` 是防碎片化复漂移的 golden 守护;新增归一化入口必须过它。
- (历史:旧的 `_CODE_PREFIX_ALT` 叙述已废,统一到 code_norm。)

## 索引管线与重建

构建器在 `pipeline/`,调度 `pipeline_orchestrator.py`(C1 严格串行链):
`kb_search_index`(分段基座)→ `kb_term_index` → `kb_build_phrase_model` → `kb_body_bm25` →
`kb_ppr_graph` → `kb_clause_index` → cross_refs / image_index →
`[--embed-clauses] kb_sentence_vectors`(付费 BGE-M3,opt-in + SILICONFLOW_API_KEY 门控,默认跳过)。

- **分段基座 `kb_search_index.py`**:MD `#` 标题 + **叶子条款分段**(扫正文行首 `^\d+\.\d+\.\d+` 补切成
  可寻址 section)。这是 clause_location 的地基——MinerU 只把短行标 `#`,实质叶子条款靠此正则补切。
- **改 kb_search_index 分段后,必按链重建** term→bm25→ppr→clause(+ 需 `--embed-clauses` 重嵌语义通道才同步)。
- 守护:`eval/pipeline_index_snapshot.py` / `pipeline_graph_snapshot.py`(产物指纹)+
  `eval/snapshot_regression.py`(**聚合召回指纹 recall@5/mrr/ndcg**,非逐条身份;这是重建后判退化的唯一可靠口径)。
  重建带 `PYTHONHASHSEED=0`;预期 diff(分段变细)人工确认后 `--update`。

## 公开能力(KB 类 / kb_loader)

- `search(query, max_results=5)`:四通道混合召回,带 trace/confidence/rank_source。
- `search_with_support(query, mode='annotate')`:叠加 support_guard 引用支撑标注。
- `read_clause(code, clause)` / `read_clause_full(code, clause, prefer_type=)`:条款正文 / 含时效+审计元数据。
- `status()` · `search_vector(query, top_k)` · `search_images(query)` · `feedback(entry)` ·
  `check(*codes)` / `exists(code)` / `get_name(code)`。

## 外部依赖与降级

- **SILICONFLOW_API_KEY**:BGE-M3 嵌入(查询向量 + 建句向量库)。未设 → 语义通道静默降级(结果无 `_clause_sim`),
  非 bug;验证语义能力必须先设。
- **ANTHROPIC_API_KEY**:LLM 重排,实为 DeepSeek 端点(`clause_refine.py`,api.deepseek.com/anthropic,deepseek-v4-flash)。
- 两 key 设在 Windows User 作用域;bash 会话不继承新设 User 变量,用
  `[Environment]::GetEnvironmentVariable(name,'User')` 读出注入。
- 句向量 `.faiss`/meta 与 `data/kb_json/*` 均 gitignore(构建产物),无版本回滚,重嵌前手动备份。

## 图谱与审计

- 代码发现优先用 semantic-memory MCP 图谱(项目 `D-zhiwei-kb-system`)。
- 图谱偶报 "project not found"——用 `index_repository`(mode=full)重建即恢复。提交新文件后应重建。
- 深改前读 `docs/tasks/CURRENT_STATE_INDEX.md`(审计台账)+ 项目 ADR 记忆(归一化统一 / 叶子分段 / 语义通道复归)。

## 验证命令

```powershell
# 语法
python -m py_compile kb_core\kb_resolver_core.py kb_core\code_norm.py pipeline\kb_search_index.py

# 归一化一致性(全绿=所有入口收敛单一真源)
$env:PYTHONHASHSEED="0"; $env:PYTHONIOENCODING="utf-8"
python eval\code_norm_consistency.py

# 检索主干回归(聚合召回指纹;重建后先跑, 预期 diff 确认再 --update)
python eval\snapshot_regression.py

# 质量门(退化 exit 1)
python pipeline\kb_search_quality.py --check

# 真值评测(需两 key; 当前 Clause@3≈0.85 / Fact@3≈0.45)
python eval\kb_truth_eval.py
```

Smoke:
```python
from kb_core.kb import KB
kb = KB()
kb.search('GB 50204', max_results=3)
kb.search('临时消防给水 1000m2', max_results=3)
kb.read_clause_full('GBT50720', '5.3.4')
```
注意:`__verify_chain` 已归档(勿再用 `python -m kb_core.__verify_chain`)。
控制台是 gbk,含 `✓` 等字符的输出用 `PYTHONIOENCODING=utf-8` 避免崩。

## 运行约束

- 只经 `kb_core/kb.json` 解析路径,不硬编码替代路径。
- 不编辑 `data/index/`、`data/md_lib_v2/` 知识库正文本体,除非用户明确要求数据修复。
- 检索优化不改公开参数/缓存 key/返回字段/排序策略/异常吞吐,除非用户明确要求行为变更。
- 一次只改一处,跑守护比基线,退化即回退;骨架(四通道/叶子分段/归一化真源)不动。
- 方案编制交给 `zhiwei-plan-writer`。
