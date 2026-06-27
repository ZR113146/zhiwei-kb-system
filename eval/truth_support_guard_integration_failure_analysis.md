# Truth Failure Analysis

Generated: 2026-06-21T13:37:30
Failed queries at @3: 13 / 20

## Category Counts

- clause_location_failure: 2
- fact_support_failure: 5
- recall_failure: 3
- version_or_forbidden_failure: 3

## Recommended T4 Focus

- version_or_forbidden_failure
- fact_support_failure
- clause_location_failure

## Per Query Attribution

- truth_0001 `临时室外消防给水系统 1000m2`: recall_failure; reasons=standard_not_hit,clause_not_hit,required_fact_not_hit; top=DBE3720 36.1.1 建筑给水排水及供暖工程设计图例; rank_source=legacy; status=unknown; judgment=manual_review; action=manual_review; missing=standard,clause,fact; simulated_top=DBE3720 36.1.1 建筑给水排水及供暖工程设计图例; simulated_action=manual_review; simulated_weight=0.55; simulated_score=109.36497
- truth_0003 `混凝土养护要求应引用 GB50204 哪一条`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法; rank_source=legacy; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=clause,fact; simulated_top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=80.7
- truth_0005 `CJJ/T 287-2018 第5.2.10条 5℃ 冬季保护`: version_or_forbidden_failure; reasons=required_fact_not_hit,forbidden_hit; top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; rank_source=md_clause_direct; status=effective; judgment=insufficient_support; action=block_forbidden; missing=fact,forbidden; simulated_top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; simulated_action=block_forbidden; simulated_weight=0.1; simulated_score=10.5
- truth_0006 `CJJ/T 287-2018 第5.2.10条 1.2m 树干包裹`: version_or_forbidden_failure; reasons=required_fact_not_hit,forbidden_hit; top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; rank_source=md_clause_direct; status=effective; judgment=insufficient_support; action=block_forbidden; missing=fact,forbidden; simulated_top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; simulated_action=block_forbidden; simulated_weight=0.1; simulated_score=10.5
- truth_0009 `JGJ 79-2012 第4.3.2条 大于0.5m`: fact_support_failure; reasons=required_fact_not_hit; top=JGJ79 4.3.2 垫层的施工方法、分层铺填厚度、每层压实遍数宜通过现场试验确定。除接触下卧软土层的垫层底部应根据施工机械设备及下卧层土质条件确定厚度外，其他垫层的分层铺填厚度宜为200mm～300mm。为保证分层压实质量，应控制机械碾压速度。; rank_source=md_clause_direct; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=JGJ79 4.3.2 垫层的施工方法、分层铺填厚度、每层压实遍数宜通过现场试验确定。除接触下卧软土层的垫层底部应根据施工机械设备及下卧层土质条件确定厚度外，其他垫层的分层铺填厚度宜为200mm～300mm。为保证分层压实质量，应控制机械碾压速度。; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=83.475
- truth_0010 `JGJ33-2012 第4.1.5条 地面承载力荷载值`: version_or_forbidden_failure; reasons=required_fact_not_hit,forbidden_hit; top=JGJ33 4.1.5 建筑起重机械的装拆应由具有起重设备安装工程承包资质的单位施工，操作和维修人员应持证上岗。; rank_source=md_clause_direct; status=effective; judgment=insufficient_support; action=block_forbidden; missing=fact,forbidden; simulated_top=JGJ33 4.1.5 建筑起重机械的装拆应由具有起重设备安装工程承包资质的单位施工，操作和维修人员应持证上岗。; simulated_action=block_forbidden; simulated_weight=0.1; simulated_score=10.815
- truth_0011 `GB 50666-2011 第4.5.2条 模板拆除强度`: fact_support_failure; reasons=required_fact_not_hit; top=GB50666 4.5.2 底模及支架应在混凝土强度达到设计要求后再拆除；当设计无具体要求时，同条件养护的混凝土立方体试件抗压强度应符合表 4.5.2 的规定。; rank_source=md_clause_direct; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB50666 4.5.2 底模及支架应在混凝土强度达到设计要求后再拆除；当设计无具体要求时，同条件养护的混凝土立方体试件抗压强度应符合表 4.5.2 的规定。; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=87.4125
- truth_0012 `GB 50202-2018 附录A 能否作为正文规范依据`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=GB50202 3.0.2 本条给出了验收时需要提供的材料,验收材料应提交齐全。; rank_source=legacy; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=clause,fact; simulated_top=GB50202 3.0.2 本条给出了验收时需要提供的材料,验收材料应提交齐全。; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=34.466987
- truth_0013 `GB 50209-2010 第6.1.5条 成品保护`: fact_support_failure; reasons=required_fact_not_hit; top=GB50209 6.1.5 铺设水泥混凝土板块、水磨石板块、人造石板块、陶瓷锦砖、陶瓷地砖、缸砖、水泥花砖、料石、大理石、花岗石等面层的结合层和填缝材料采用水泥砂浆时，在面层铺设后，表面应覆盖、湿润，养护时间不应少于7d。当板块面层的水泥砂浆结合层的抗压强度达到设计要求后，方可正常使用。; rank_source=md_clause_direct; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB50209 6.1.5 铺设水泥混凝土板块、水磨石板块、人造石板块、陶瓷锦砖、陶瓷地砖、缸砖、水泥花砖、料石、大理石、花岗石等面层的结合层和填缝材料采用水泥砂浆时，在面层铺设后，表面应覆盖、湿润，养护时间不应少于7d。当板块面层的水泥砂浆结合层的抗压强度达到设计要求后，方可正常使用。; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=81.1125
- truth_0015 `DB323700 第1.0.1条`: recall_failure; reasons=standard_not_hit,clause_not_hit; top=GB50011 3.10.3 建筑结构的抗震性能化设计应符合下列要求：; rank_source=legacy; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=standard,clause; simulated_top=GB50011 3.10.3 建筑结构的抗震性能化设计应符合下列要求：; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=7.84875
- truth_0016 `钢筋保护层厚度 施工要求`: fact_support_failure; reasons=required_fact_not_hit; top=GB50003 4.3.3: 保护层厚度 = 0mm ; rank_source=param_index; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB50003 4.3.3: 保护层厚度 = 0mm ; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=64.2
- truth_0018 `基坑支护 验收标准`: recall_failure; reasons=no_results,standard_not_hit,clause_not_hit,required_fact_not_hit; top= ; rank_source=; status=; judgment=; action=; missing=-; simulated_top= ; simulated_action=; simulated_weight=; simulated_score=
- truth_0020 `条文说明 能作为验收依据吗`: fact_support_failure; reasons=required_fact_not_hit; top=GB50303 3.4.3 当验收建筑电气工程时，应核查下列各项质量控制资料，且资料内容应真实、齐全、完整：; rank_source=legacy; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB50303 3.4.3 当验收建筑电气工程时，应核查下列各项质量控制资料，且资料内容应真实、齐全、完整：; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=126.763943

## Phase Questions

1. This phase serves reliable professional answers by judging support against truth answers, not only search relevance.
2. It validates deterministic standard/clause/fact/version/forbidden signals; it does not validate full semantic table reasoning or LLM answer grading.
3. It does not extend plan writing, Word output, or generic search tuning.
4. The most dangerous current error type is the highest-risk category listed in Recommended T4 Focus, especially forbidden/deleted or high-score unsupported evidence.
5. Next step should target only the selected T4 categories because tuning before attribution would hide the actual failure mechanism.
