# Zhiwei KB Truth Baseline

Generated: 2026-06-21T13:37:30
Truth queries: 20

## Overall

- TruthSupport@1: 0.35
- TruthSupport@3: 0.35
- Clause@3: 0.75
- Fact@3: 0.4
- ForbiddenHitRate: 0.15
- DeletedClauseErrorRate: 0.05
- StaleVersionErrorRate: 0.0
- TableCellHitRate: 1.0
- UnsupportedHighScoreRate: 0.6
- AvgLatency: 530.08
- Errors: 0
- UnsupportedHighScoreGuardedRate: 1.0
- SimulatedTruthSupport@1: 0.35
- SimulatedUnsupportedHighScoreRate: 0.6
- SupportGuardTop1ChangedRate: 0.0
- ForbiddenBlockedRate: 0.75
- EvidenceUseRate: 0.35
- ManualReviewRate: 0.05
- SimulatedBlockedTop1Rate: 0.15

## By Query Type

- appendix_intent: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=448.99
- broad_technical: support@1=0.5 support@3=0.5 clause@3=0.75 fact@3=0.5 unsupported_high=0.25 avg_ms=420.76
- clause_lookup: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=1.0 unsupported_high=1.0 avg_ms=448.45
- clause_support: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=27.09
- deleted_clause: support@1=1.0 support@3=1.0 clause@3=1.0 fact@3=1.0 unsupported_high=0.0 avg_ms=86.34
- explanation_vs_normative: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=572.17
- fact_support: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=23.09
- nearby_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=568.78
- nearby_not_applicable: support@1=0.0 support@3=0.0 clause@3=1.0 fact@3=0.0 unsupported_high=1.0 avg_ms=21.91
- parameter_clause: support@1=0.0 support@3=0.0 clause@3=0.0 fact@3=0.0 unsupported_high=1.0 avg_ms=6601.16
- standard_name: support@1=1.0 support@3=1.0 clause@3=1.0 fact@3=1.0 unsupported_high=0.0 avg_ms=1.32
- subitem_clause: support@1=1.0 support@3=1.0 clause@3=1.0 fact@3=1.0 unsupported_high=0.0 avg_ms=21.79
- table_cell: support@1=1.0 support@3=1.0 clause@3=1.0 fact@3=1.0 unsupported_high=0.0 avg_ms=23.94
- version_status: support@1=1.0 support@3=1.0 clause@3=1.0 fact@3=1.0 unsupported_high=0.0 avg_ms=1.39

## Failure Categories

- clause_location_failure: 2
- fact_support_failure: 5
- recall_failure: 3
- supported: 7
- version_or_forbidden_failure: 3

## Failed Or Risky Queries

- truth_0001 `临时室外消防给水系统 1000m2`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit,required_fact_not_hit top=DBE3720 36.1.1 建筑给水排水及供暖工程设计图例 judgment=manual_review missing=standard,clause,fact action=manual_review simulated_top=DBE3720 36.1.1 建筑给水排水及供暖工程设计图例 simulated_action=manual_review
- truth_0003 `混凝土养护要求应引用 GB50204 哪一条`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法 judgment=insufficient_support missing=clause,fact action=warn_insufficient_support simulated_top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法 simulated_action=warn_insufficient_support
- truth_0005 `CJJ/T 287-2018 第5.2.10条 5℃ 冬季保护`: category=version_or_forbidden_failure support@3=False reasons=required_fact_not_hit,forbidden_hit top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定： judgment=insufficient_support missing=fact,forbidden action=block_forbidden simulated_top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定： simulated_action=block_forbidden
- truth_0006 `CJJ/T 287-2018 第5.2.10条 1.2m 树干包裹`: category=version_or_forbidden_failure support@3=False reasons=required_fact_not_hit,forbidden_hit top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定： judgment=insufficient_support missing=fact,forbidden action=block_forbidden simulated_top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定： simulated_action=block_forbidden
- truth_0009 `JGJ 79-2012 第4.3.2条 大于0.5m`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=JGJ79 4.3.2 垫层的施工方法、分层铺填厚度、每层压实遍数宜通过现场试验确定。除接触下卧软土层的垫层底部应根据施工机械设备及下卧层土质条件确定厚度外，其他垫层的分层铺填厚度宜为200mm～300mm。为保证分层压实质量，应控制机械碾压速度。 judgment=insufficient_support missing=fact action=warn_insufficient_support simulated_top=JGJ79 4.3.2 垫层的施工方法、分层铺填厚度、每层压实遍数宜通过现场试验确定。除接触下卧软土层的垫层底部应根据施工机械设备及下卧层土质条件确定厚度外，其他垫层的分层铺填厚度宜为200mm～300mm。为保证分层压实质量，应控制机械碾压速度。 simulated_action=warn_insufficient_support
- truth_0010 `JGJ33-2012 第4.1.5条 地面承载力荷载值`: category=version_or_forbidden_failure support@3=False reasons=required_fact_not_hit,forbidden_hit top=JGJ33 4.1.5 建筑起重机械的装拆应由具有起重设备安装工程承包资质的单位施工，操作和维修人员应持证上岗。 judgment=insufficient_support missing=fact,forbidden action=block_forbidden simulated_top=JGJ33 4.1.5 建筑起重机械的装拆应由具有起重设备安装工程承包资质的单位施工，操作和维修人员应持证上岗。 simulated_action=block_forbidden
- truth_0011 `GB 50666-2011 第4.5.2条 模板拆除强度`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50666 4.5.2 底模及支架应在混凝土强度达到设计要求后再拆除；当设计无具体要求时，同条件养护的混凝土立方体试件抗压强度应符合表 4.5.2 的规定。 judgment=insufficient_support missing=fact action=warn_insufficient_support simulated_top=GB50666 4.5.2 底模及支架应在混凝土强度达到设计要求后再拆除；当设计无具体要求时，同条件养护的混凝土立方体试件抗压强度应符合表 4.5.2 的规定。 simulated_action=warn_insufficient_support
- truth_0012 `GB 50202-2018 附录A 能否作为正文规范依据`: category=clause_location_failure support@3=False reasons=clause_not_hit,required_fact_not_hit top=GB50202 3.0.2 本条给出了验收时需要提供的材料,验收材料应提交齐全。 judgment=insufficient_support missing=clause,fact action=warn_insufficient_support simulated_top=GB50202 3.0.2 本条给出了验收时需要提供的材料,验收材料应提交齐全。 simulated_action=warn_insufficient_support
- truth_0013 `GB 50209-2010 第6.1.5条 成品保护`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50209 6.1.5 铺设水泥混凝土板块、水磨石板块、人造石板块、陶瓷锦砖、陶瓷地砖、缸砖、水泥花砖、料石、大理石、花岗石等面层的结合层和填缝材料采用水泥砂浆时，在面层铺设后，表面应覆盖、湿润，养护时间不应少于7d。当板块面层的水泥砂浆结合层的抗压强度达到设计要求后，方可正常使用。 judgment=insufficient_support missing=fact action=warn_insufficient_support simulated_top=GB50209 6.1.5 铺设水泥混凝土板块、水磨石板块、人造石板块、陶瓷锦砖、陶瓷地砖、缸砖、水泥花砖、料石、大理石、花岗石等面层的结合层和填缝材料采用水泥砂浆时，在面层铺设后，表面应覆盖、湿润，养护时间不应少于7d。当板块面层的水泥砂浆结合层的抗压强度达到设计要求后，方可正常使用。 simulated_action=warn_insufficient_support
- truth_0015 `DB323700 第1.0.1条`: category=recall_failure support@3=False reasons=standard_not_hit,clause_not_hit top=GB50011 3.10.3 建筑结构的抗震性能化设计应符合下列要求： judgment=insufficient_support missing=standard,clause action=warn_insufficient_support simulated_top=GB50011 3.10.3 建筑结构的抗震性能化设计应符合下列要求： simulated_action=warn_insufficient_support
- truth_0016 `钢筋保护层厚度 施工要求`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50003 4.3.3: 保护层厚度 = 0mm  judgment=insufficient_support missing=fact action=warn_insufficient_support simulated_top=GB50003 4.3.3: 保护层厚度 = 0mm  simulated_action=warn_insufficient_support
- truth_0018 `基坑支护 验收标准`: category=recall_failure support@3=False reasons=no_results,standard_not_hit,clause_not_hit,required_fact_not_hit top=  judgment= missing=- action= simulated_top=  simulated_action=
- truth_0020 `条文说明 能作为验收依据吗`: category=fact_support_failure support@3=False reasons=required_fact_not_hit top=GB50303 3.4.3 当验收建筑电气工程时，应核查下列各项质量控制资料，且资料内容应真实、齐全、完整： judgment=insufficient_support missing=fact action=warn_insufficient_support simulated_top=GB50303 3.4.3 当验收建筑电气工程时，应核查下列各项质量控制资料，且资料内容应真实、齐全、完整： simulated_action=warn_insufficient_support
