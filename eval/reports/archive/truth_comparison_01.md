# Zhiwei KB Truth Baseline

Generated: 2026-06-19T17:09:02
Truth queries: 20

## Overall

- TruthSupport@1: 0.0
- TruthSupport@3: 0.0
- Clause@3: 0.35
- Fact@3: 0.1
- ForbiddenHitRate: 0.0
- DeletedClauseErrorRate: 0.0
- StaleVersionErrorRate: 0.0
- TableCellHitRate: 0.0
- UnsupportedHighScoreRate: 0.95
- AvgLatency: 3178.34
- Errors: 0

## By Query Type

- appendix_intent: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2355.55
- broad_technical: support@1=0.0 support@3=0.0 clause@3=0.75 fact@3=0.0 unsupported_high=0.75 avg_ms=2742.38
- clause_lookup: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=1.0 unsupported_high=1.0 avg_ms=3013.03
- clause_support: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.5 unsupported_high=1.0 avg_ms=2020.37
- deleted_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2099.44
- explanation_vs_normative: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=5699.29
- fact_support: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2501.13
- nearby_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2703.98
- nearby_not_applicable: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=3642.88
- parameter_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=14668.91
- standard_name: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=1.48
- subitem_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2683.08
- table_cell: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=3042.22
- version_status: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=1.47

## Failure Categories

- clause_location_failure: 8
- fact_support_failure: 6
- recall_failure: 5
- table_location_failure: 1

## Failed Or Risky Queries

- truth_0001 `临时室外消防给水系统 1000m2`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit,required_fact_not_hit top=GB50268 4.1.9 给排水管道铺设完毕并经检验合格后，应及时回填沟槽。回填前，应符合下列规定：
- truth_0002 `GB/T 50720-2011 第5.1.4条还能作为临时消防给水依据吗`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GBT50720 建设工程施工现场消防安全技术标准
- truth_0003 `混凝土养护要求应引用 GB50204 哪一条`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法
- truth_0004 `GB50209 6.1.8 大于1.0mm 表格值`: category=table_location_failure support@3=False reasons=required_fact_not_hit top=GB50209 6.4.14 水泥混凝土板块、水磨石板块、人造石板块面层的允许偏差应符合本规范表 6.1.8 的规定。
- truth_0005 `CJJ/T 287-2018 第5.2.10条 5℃ 冬季保护`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=CJJT287 引用标准名录
- truth_0006 `CJJ/T 287-2018 第5.2.10条 1.2m 树干包裹`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=CJJT287 引用标准名录
- truth_0007 `CJJ/T 287-2018 第5.2.8条 0.1m 苗木保护`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=CJJT287 4.1 园林绿化养护管理分级
- truth_0008 `天然石材防护剂 GB/T 32837-2016`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GBT32837 _seg0_GB_T 32837-2016 天然石材防护剂
- truth_0009 `JGJ 79-2012 第4.3.2条 大于0.5m`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=JGJ79 建筑地基处理技术规范
- truth_0010 `JGJ33-2012 第4.1.5条 地面承载力荷载值`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit,required_fact_not_hit top=GB50210 附录 A 建筑装饰装修工程的子分部 工程、分项工程划分
- truth_0011 `GB 50666-2011 第4.5.2条 模板拆除强度`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit,required_fact_not_hit top= : 模板拆除 = 20MPa 
- truth_0012 `GB 50202-2018 附录A 能否作为正文规范依据`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GB50202 3.0.2 本条给出了验收时需要提供的材料,验收材料应提交齐全。
- truth_0013 `GB 50209-2010 第6.1.5条 成品保护`: category=clause_location_failure support@3=False reasons=clause_not_hit top= 5.2 成品保护 · 90
- truth_0014 `DB323700 江苏省城市轨道交通工程设计标准 现行吗`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=DB323700 江苏省城市轨道交通工程设计标准
- truth_0015 `DB323700 第1.0.1条`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit top=GB50011 3.10.3 建筑结构的抗震性能化设计应符合下列要求：
- truth_0016 `钢筋保护层厚度 施工要求`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50003 4.3.3: 保护层厚度 = 0mm 
- truth_0017 `给排水 施工要求`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50268 4.1.9 给排水管道铺设完毕并经检验合格后，应及时回填沟槽。回填前，应符合下列规定：
- truth_0018 `基坑支护 验收标准`: category=recall_failure support@3=False reasons=no_results,standard_not_hit,clause_not_hit,required_fact_not_hit top= 
- truth_0019 `脚手架 验收标准`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=JGJT231 2.1.2 支撑脚手架 shoring scaffold
- truth_0020 `条文说明 能作为验收依据吗`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50303 3.4.3 当验收建筑电气工程时，应核查下列各项质量控制资料，且资料内容应真实、齐全、完整：
