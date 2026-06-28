# Zhiwei KB Truth Baseline

Generated: 2026-06-19T18:33:29
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
- AvgLatency: 2472.9
- Errors: 0
- UnsupportedHighScoreGuardedRate: 1.0
- ForbiddenBlockedRate: None
- EvidenceUseRate: 0.0
- ManualReviewRate: 0.15

## By Query Type

- appendix_intent: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2643.61
- broad_technical: support@1=0.0 support@3=0.0 clause@3=0.75 fact@3=0.0 unsupported_high=0.75 avg_ms=2094.92
- clause_lookup: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=1.0 unsupported_high=1.0 avg_ms=2697.84
- clause_support: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.5 unsupported_high=1.0 avg_ms=1059.75
- deleted_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=4238.79
- explanation_vs_normative: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=5171.9
- fact_support: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2468.18
- nearby_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2759.22
- nearby_not_applicable: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=1830.24
- parameter_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=8685.05
- standard_name: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=1.29
- subitem_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=1952.81
- table_cell: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=2209.66
- version_status: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=1.7

## Failure Categories

- clause_location_failure: 8
- fact_support_failure: 6
- recall_failure: 5
- table_location_failure: 1

## Failed Or Risky Queries

- truth_0001 `临时室外消防给水系统 1000m2`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit,required_fact_not_hit top=DBE3720 36.1.1 建筑给水排水及供暖工程设计图例 judgment=需复核 missing=standard,clause,fact action=manual_review
- truth_0002 `GB/T 50720-2011 第5.1.4条还能作为临时消防给水依据吗`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GBT50720 建设工程施工现场消防安全技术标准 judgment=不足以支撑 missing=clause,fact action=warn_insufficient_support
- truth_0003 `混凝土养护要求应引用 GB50204 哪一条`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法 judgment=不足以支撑 missing=clause,fact action=warn_insufficient_support
- truth_0004 `GB50209 6.1.8 大于1.0mm 表格值`: category=table_location_failure support@3=False reasons=required_fact_not_hit top=GB50209 6.4.14 水泥混凝土板块、水磨石板块、人造石板块面层的允许偏差应符合本规范表 6.1.8 的规定。 judgment=不足以支撑 missing=fact action=warn_insufficient_support
- truth_0005 `CJJ/T 287-2018 第5.2.10条 5℃ 冬季保护`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=CJJT287 引用标准名录 judgment=不足以支撑 missing=clause,fact action=warn_insufficient_support
- truth_0006 `CJJ/T 287-2018 第5.2.10条 1.2m 树干包裹`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=CJJT287 引用标准名录 judgment=不足以支撑 missing=clause,fact action=warn_insufficient_support
- truth_0007 `CJJ/T 287-2018 第5.2.8条 0.1m 苗木保护`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=CJJT287 4.1 园林绿化养护管理分级 judgment=不足以支撑 missing=clause,fact action=warn_insufficient_support
- truth_0008 `天然石材防护剂 GB/T 32837-2016`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GBT32837 _seg0_GB_T 32837-2016 天然石材防护剂 judgment=不足以支撑 missing=fact action=warn_insufficient_support
- truth_0009 `JGJ 79-2012 第4.3.2条 大于0.5m`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=JGJ79 建筑地基处理技术规范 judgment=不足以支撑 missing=clause,fact action=warn_insufficient_support
- truth_0010 `JGJ33-2012 第4.1.5条 地面承载力荷载值`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit,required_fact_not_hit top=GB50210 附录 A 建筑装饰装修工程的子分部 工程、分项工程划分 judgment=需复核 missing=standard,clause,fact action=manual_review
- truth_0011 `GB 50666-2011 第4.5.2条 模板拆除强度`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit,required_fact_not_hit top= : 模板拆除 = 20MPa  judgment=需复核 missing=standard,clause,fact action=manual_review
- truth_0012 `GB 50202-2018 附录A 能否作为正文规范依据`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GB50202 3.0.2 本条给出了验收时需要提供的材料,验收材料应提交齐全。 judgment=不足以支撑 missing=clause,fact action=warn_insufficient_support
- truth_0013 `GB 50209-2010 第6.1.5条 成品保护`: category=clause_location_failure support@3=False reasons=clause_not_hit top= 5.2 成品保护 · 90 judgment=不足以支撑 missing=standard,clause action=warn_insufficient_support
- truth_0014 `DB323700 江苏省城市轨道交通工程设计标准 现行吗`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=DB323700 江苏省城市轨道交通工程设计标准 judgment=不足以支撑 missing=fact action=warn_insufficient_support
- truth_0015 `DB323700 第1.0.1条`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit top=GB50011 3.10.3 建筑结构的抗震性能化设计应符合下列要求： judgment=不足以支撑 missing=standard,clause action=warn_insufficient_support
- truth_0016 `钢筋保护层厚度 施工要求`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50003 4.3.3: 保护层厚度 = 0mm  judgment=不足以支撑 missing=fact action=warn_insufficient_support
- truth_0017 `给排水 施工要求`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50268 4.1.9 给排水管道铺设完毕并经检验合格后，应及时回填沟槽。回填前，应符合下列规定： judgment=不足以支撑 missing=fact action=warn_insufficient_support
- truth_0018 `基坑支护 验收标准`: category=recall_failure support@3=False reasons=no_results,standard_not_hit,clause_not_hit,required_fact_not_hit top=  judgment= missing=- action=
- truth_0019 `脚手架 验收标准`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=JGJT231 2.1.2 支撑脚手架 shoring scaffold judgment=不足以支撑 missing=fact action=warn_insufficient_support
- truth_0020 `条文说明 能作为验收依据吗`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50303 3.4.3 当验收建筑电气工程时，应核查下列各项质量控制资料，且资料内容应真实、齐全、完整： judgment=不足以支撑 missing=fact action=warn_insufficient_support
