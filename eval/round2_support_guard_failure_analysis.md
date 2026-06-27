# Truth Failure Analysis

Generated: 2026-06-19T18:33:29
Failed queries at @3: 20 / 20

## Category Counts

- clause_location_failure: 8
- fact_support_failure: 6
- recall_failure: 5
- table_location_failure: 1

## Recommended T4 Focus

- fact_support_failure
- table_location_failure
- clause_location_failure

## Per Query Attribution

- truth_0001 `临时室外消防给水系统 1000m2`: recall_failure; reasons=standard_not_hit,clause_not_hit,required_fact_not_hit; top=DBE3720 36.1.1 建筑给水排水及供暖工程设计图例; rank_source=legacy; status=unknown; judgment=需复核; action=manual_review; missing=standard,clause,fact
- truth_0002 `GB/T 50720-2011 第5.1.4条还能作为临时消防给水依据吗`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=GBT50720 建设工程施工现场消防安全技术标准; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=clause,fact
- truth_0003 `混凝土养护要求应引用 GB50204 哪一条`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=GB50204 7.1.1 材料试验主要参数、取样规则及取样方法; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=clause,fact
- truth_0004 `GB50209 6.1.8 大于1.0mm 表格值`: table_location_failure; reasons=required_fact_not_hit; top=GB50209 6.4.14 水泥混凝土板块、水磨石板块、人造石板块面层的允许偏差应符合本规范表 6.1.8 的规定。; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=fact
- truth_0005 `CJJ/T 287-2018 第5.2.10条 5℃ 冬季保护`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=CJJT287 引用标准名录; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=clause,fact
- truth_0006 `CJJ/T 287-2018 第5.2.10条 1.2m 树干包裹`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=CJJT287 引用标准名录; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=clause,fact
- truth_0007 `CJJ/T 287-2018 第5.2.8条 0.1m 苗木保护`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=CJJT287 4.1 园林绿化养护管理分级; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=clause,fact
- truth_0008 `天然石材防护剂 GB/T 32837-2016`: fact_support_failure; reasons=required_fact_not_hit; top=GBT32837 _seg0_GB_T 32837-2016 天然石材防护剂; rank_source=filename_title; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=fact
- truth_0009 `JGJ 79-2012 第4.3.2条 大于0.5m`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=JGJ79 建筑地基处理技术规范; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=clause,fact
- truth_0010 `JGJ33-2012 第4.1.5条 地面承载力荷载值`: recall_failure; reasons=standard_not_hit,clause_not_hit,required_fact_not_hit; top=GB50210 附录 A 建筑装饰装修工程的子分部 工程、分项工程划分; rank_source=legacy; status=effective; judgment=需复核; action=manual_review; missing=standard,clause,fact
- truth_0011 `GB 50666-2011 第4.5.2条 模板拆除强度`: recall_failure; reasons=standard_not_hit,clause_not_hit,required_fact_not_hit; top= : 模板拆除 = 20MPa ; rank_source=param_index; status=unknown; judgment=需复核; action=manual_review; missing=standard,clause,fact
- truth_0012 `GB 50202-2018 附录A 能否作为正文规范依据`: clause_location_failure; reasons=clause_not_hit,required_fact_not_hit; top=GB50202 3.0.2 本条给出了验收时需要提供的材料,验收材料应提交齐全。; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=clause,fact
- truth_0013 `GB 50209-2010 第6.1.5条 成品保护`: clause_location_failure; reasons=clause_not_hit; top= 5.2 成品保护 · 90; rank_source=legacy; status=unknown; judgment=不足以支撑; action=warn_insufficient_support; missing=standard,clause
- truth_0014 `DB323700 江苏省城市轨道交通工程设计标准 现行吗`: fact_support_failure; reasons=required_fact_not_hit; top=DB323700 江苏省城市轨道交通工程设计标准; rank_source=standard_status_direct; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=fact
- truth_0015 `DB323700 第1.0.1条`: recall_failure; reasons=standard_not_hit,clause_not_hit; top=GB50011 3.10.3 建筑结构的抗震性能化设计应符合下列要求：; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=standard,clause
- truth_0016 `钢筋保护层厚度 施工要求`: fact_support_failure; reasons=required_fact_not_hit; top=GB50003 4.3.3: 保护层厚度 = 0mm ; rank_source=param_index; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=fact
- truth_0017 `给排水 施工要求`: fact_support_failure; reasons=required_fact_not_hit; top=GB50268 4.1.9 给排水管道铺设完毕并经检验合格后，应及时回填沟槽。回填前，应符合下列规定：; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=fact
- truth_0018 `基坑支护 验收标准`: recall_failure; reasons=no_results,standard_not_hit,clause_not_hit,required_fact_not_hit; top= ; rank_source=; status=; judgment=; action=; missing=-
- truth_0019 `脚手架 验收标准`: fact_support_failure; reasons=required_fact_not_hit; top=JGJT231 2.1.2 支撑脚手架 shoring scaffold; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=fact
- truth_0020 `条文说明 能作为验收依据吗`: fact_support_failure; reasons=required_fact_not_hit; top=GB50303 3.4.3 当验收建筑电气工程时，应核查下列各项质量控制资料，且资料内容应真实、齐全、完整：; rank_source=legacy; status=effective; judgment=不足以支撑; action=warn_insufficient_support; missing=fact

## Phase Questions

1. This phase serves reliable professional answers by judging support against truth answers, not only search relevance.
2. It validates deterministic standard/clause/fact/version/forbidden signals; it does not validate full semantic table reasoning or LLM answer grading.
3. It does not extend plan writing, Word output, or generic search tuning.
4. The most dangerous current error type is the highest-risk category listed in Recommended T4 Focus, especially forbidden/deleted or high-score unsupported evidence.
5. Next step should target only the selected T4 categories because tuning before attribution would hide the actual failure mechanism.
