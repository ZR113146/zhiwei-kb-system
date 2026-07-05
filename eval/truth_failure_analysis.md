# Truth Failure Analysis

Generated: 2026-07-05T20:45:35
Failed queries at @3: 12 / 20

## Category Counts

- clause_location_failure: 3
- fact_support_failure: 5
- recall_failure: 1
- version_or_forbidden_failure: 3

## Recommended T4 Focus

- version_or_forbidden_failure
- fact_support_failure
- clause_location_failure

## Per Query Attribution

- truth_0003 `混凝土养护要求应引用 GB50204 哪一条`: clause_location_failure; reasons=clause_not_hit; top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法; rank_source=legacy; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=clause,fact; simulated_top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=80.7
- truth_0005 `CJJ/T 287-2018 第5.2.10条 5℃ 冬季保护`: version_or_forbidden_failure; reasons=required_fact_not_hit,forbidden_hit; top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; rank_source=clause_index; status=effective; judgment=insufficient_support; action=block_forbidden; missing=fact,forbidden; simulated_top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; simulated_action=block_forbidden; simulated_weight=0.1; simulated_score=10.0
- truth_0006 `CJJ/T 287-2018 第5.2.10条 1.2m 树干包裹`: version_or_forbidden_failure; reasons=required_fact_not_hit,forbidden_hit; top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; rank_source=clause_index; status=effective; judgment=insufficient_support; action=block_forbidden; missing=fact,forbidden; simulated_top=CJJT287 5.2.10 树木有害生物防治的原则、方法应符合下列规定：; simulated_action=block_forbidden; simulated_weight=0.1; simulated_score=10.0
- truth_0009 `JGJ 79-2012 第4.3.2条 大于0.5m`: fact_support_failure; reasons=required_fact_not_hit; top=JGJ79 4.3.2 垫层的施工方法、分层铺填厚度、每层压实遍数宜通过现场试验确定。除接触下卧软土层的垫层底部应根据施工机械设备及下卧层土质条件确定厚度外，其他垫层的分层铺填厚度宜为200mm～300mm。为保证分层压实质量，应控制机械碾压速度。; rank_source=clause_index; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=JGJ79 4.3.2 垫层的施工方法、分层铺填厚度、每层压实遍数宜通过现场试验确定。除接触下卧软土层的垫层底部应根据施工机械设备及下卧层土质条件确定厚度外，其他垫层的分层铺填厚度宜为200mm～300mm。为保证分层压实质量，应控制机械碾压速度。; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=79.5
- truth_0010 `JGJ33-2012 第4.1.5条 地面承载力荷载值`: version_or_forbidden_failure; reasons=required_fact_not_hit,forbidden_hit; top=JGJ33 4.1.5 建筑起重机械的装拆应由具有起重设备安装工程承包资质的单位施工，操作和维修人员应持证上岗。; rank_source=clause_index; status=effective; judgment=insufficient_support; action=block_forbidden; missing=fact,forbidden; simulated_top=JGJ33 4.1.5 建筑起重机械的装拆应由具有起重设备安装工程承包资质的单位施工，操作和维修人员应持证上岗。; simulated_action=block_forbidden; simulated_weight=0.1; simulated_score=10.3
- truth_0011 `GB 50666-2011 第4.5.2条 模板拆除强度`: fact_support_failure; reasons=required_fact_not_hit; top=GB50666 4.5.2 底模及支架应在混凝土强度达到设计要求后再拆除；当设计无具体要求时，同条件养护的混凝土立方体试件抗压强度应符合表 4.5.2 的规定。; rank_source=clause_index; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB50666 4.5.2 底模及支架应在混凝土强度达到设计要求后再拆除；当设计无具体要求时，同条件养护的混凝土立方体试件抗压强度应符合表 4.5.2 的规定。; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=83.25
- truth_0012 `GB 50202-2018 附录A 能否作为正文规范依据`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=GB50202 3.0.6 检查数量应按检验批抽样,当本标准有具体规定时,应按相应条款执行,无规定时应按检验批抽检。检验批的划分和检验批抽检数量可按照现行国家标准《建筑工程施工质量验收统一标准》GB 50300 的规定执行。; rank_source=legacy; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=clause,fact; simulated_top=GB50202 3.0.6 检查数量应按检验批抽样,当本标准有具体规定时,应按相应条款执行,无规定时应按检验批抽检。检验批的划分和检验批抽检数量可按照现行国家标准《建筑工程施工质量验收统一标准》GB 50300 的规定执行。; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=34.645066
- truth_0013 `GB 50209-2010 第6.1.5条 成品保护`: fact_support_failure; reasons=required_fact_not_hit; top=GB50209 6.1.5 铺设水泥混凝土板块、水磨石板块、人造石板块、陶瓷锦砖、陶瓷地砖、缸砖、水泥花砖、料石、大理石、花岗石等面层的结合层和填缝材料采用水泥砂浆时，在面层铺设后，表面应覆盖、湿润，养护时间不应少于7d。当板块面层的水泥砂浆结合层的抗压强; rank_source=clause_index; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB50209 6.1.5 铺设水泥混凝土板块、水磨石板块、人造石板块、陶瓷锦砖、陶瓷地砖、缸砖、水泥花砖、料石、大理石、花岗石等面层的结合层和填缝材料采用水泥砂浆时，在面层铺设后，表面应覆盖、湿润，养护时间不应少于7d。当板块面层的水泥砂浆结合层的抗压强; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=77.25
- truth_0015 `DB323700 第1.0.1条`: clause_location_failure; reasons=clause_not_hit; top=DB32T3700 DB32T3700; rank_source=clause_index_fallback; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=clause; simulated_top=DB32T3700 DB32T3700; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=67.5
- truth_0016 `钢筋保护层厚度 施工要求`: fact_support_failure; reasons=required_fact_not_hit; top=GB50010 8.2.1 构件中普通钢筋及预应力筋的混凝土保护层厚度应满足下列要求。; rank_source=merged+clause_refine; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB50204 6.5.4 锚具的封闭保护措施应符合设计要求。当设计无具体要求时，外露锚具和预应力筋的混凝土保护层厚度不应小于：一类环境时20mm，二a、二b类环境时50mm，; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=124.9989
- truth_0018 `基坑支护 验收标准`: recall_failure; reasons=no_results,standard_not_hit,clause_not_hit,required_fact_not_hit; top= ; rank_source=; status=; judgment=; action=; missing=-; simulated_top= ; simulated_action=; simulated_weight=; simulated_score=
- truth_0020 `条文说明 能作为验收依据吗`: fact_support_failure; reasons=required_fact_not_hit; top=GB55032 4.2.1 本条为工程施工质量验收合格的基本条件，本规范及相关专业规范提出的合格要求是对施工质量的最低要求，应允许建设、设计等单位提出高于本规范及相关专业规范的; rank_source=merged+clause_refine; status=effective; judgment=insufficient_support; action=warn_insufficient_support; missing=fact; simulated_top=GB55032 4.2.1 本条为工程施工质量验收合格的基本条件，本规范及相关专业规范提出的合格要求是对施工质量的最低要求，应允许建设、设计等单位提出高于本规范及相关专业规范的; simulated_action=warn_insufficient_support; simulated_weight=0.75; simulated_score=188.24835

## Phase Questions

1. This phase serves reliable professional answers by judging support against truth answers, not only search relevance.
2. It validates deterministic standard/clause/fact/version/forbidden signals; it does not validate full semantic table reasoning or LLM answer grading.
3. It does not extend plan writing, Word output, or generic search tuning.
4. The most dangerous current error type is the highest-risk category listed in Recommended T4 Focus, especially forbidden/deleted or high-score unsupported evidence.
5. Next step should target only the selected T4 categories because tuning before attribution would hide the actual failure mechanism.
