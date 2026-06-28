# Zhiwei KB Evaluation Baseline

Generated: 2026-06-19T15:58:54
Golden queries: 100

## Overall

- recall_at_5: 0.54
- mrr: 0.4712
- ndcg_at_10: 0.4881
- clause_hit_rate: 0.5
- no_result_rate: 0.08
- stale_hit_rate: 0.04
- avg_elapsed_ms: 3071.86
- errors: 0

## By Query Type

- clause: recall=1.0 mrr=0.6972 ndcg=0.7707 no_result=0.0 avg_ms=4894.16
- comparison: recall=1.0 mrr=0.7667 ndcg=0.8262 no_result=0.0 avg_ms=7743.24
- parameter: recall=0.0 mrr=0.0 ndcg=0.0 no_result=0.0 avg_ms=4857.59
- standard_code: recall=0.8889 mrr=0.8889 ndcg=0.8889 no_result=0.0556 avg_ms=498.24
- standard_name: recall=1.0 mrr=0.8819 ndcg=0.9109 no_result=0.0 avg_ms=2505.76
- technical: recall=0.0 mrr=0.0 ndcg=0.0 no_result=0.1935 avg_ms=2985.72
- version: recall=0.9 mrr=0.8333 ndcg=0.85 no_result=0.1 avg_ms=1985.43

## Failures

- line 1: `DB323700 现行吗` expected `DB323700` rank=None results=0 error=
- line 2: `DB323700 第1.0.1条` expected `DB323700` rank=None results=1 error=
- line 8: `钢筋保护层厚度` expected `DB323700` rank=None results=5 error=
- line 9: `钢筋保护层厚度 怎么规定` expected `DB323700` rank=None results=5 error=
- line 10: `钢筋保护层厚度` expected `DB323700` rank=None results=5 error=
- line 11: `钢筋保护层厚度 施工要求` expected `DB323700` rank=None results=5 error=
- line 12: `钢筋保护层厚度 验收标准` expected `DB323700` rank=None results=0 error=
- line 13: `钢筋保护层厚度 质量要求` expected `DB323700` rank=None results=5 error=
- line 14: `钢筋保护层厚度 设计要求` expected `DB323700` rank=None results=5 error=
- line 15: `钢筋保护层厚度 规范` expected `DB323700` rank=None results=0 error=
- line 17: `DB323700 是否废止` expected `DB323700` rank=None results=0 error=
- line 26: `给排水` expected `TCECS1229` rank=None results=10 error=
- line 27: `给排水 怎么规定` expected `TCECS1229` rank=None results=10 error=
- line 28: `给排水` expected `TCECS1229` rank=None results=10 error=
- line 29: `给排水 施工要求` expected `TCECS1229` rank=None results=10 error=
- line 30: `给排水 验收标准` expected `TCECS1229` rank=None results=0 error=
- line 31: `给排水 质量要求` expected `TCECS1229` rank=None results=10 error=
- line 32: `给排水 设计要求` expected `TCECS1229` rank=None results=10 error=
- line 33: `给排水 规范` expected `TCECS1229` rank=None results=1 error=
- line 44: `基坑支护` expected `CJJ1` rank=None results=1 error=
- line 45: `基坑支护 怎么规定` expected `CJJ1` rank=None results=10 error=
- line 46: `基坑支护` expected `CJJ1` rank=None results=1 error=
- line 47: `基坑支护 施工要求` expected `CJJ1` rank=None results=10 error=
- line 48: `基坑支护 验收标准` expected `CJJ1` rank=None results=0 error=
- line 49: `基坑支护 质量要求` expected `CJJ1` rank=None results=10 error=
- line 50: `基坑支护 设计要求` expected `CJJ1` rank=None results=10 error=
- line 51: `基坑支护 规范` expected `CJJ1` rank=None results=1 error=
- line 62: `脚手架` expected `CJJ2` rank=None results=10 error=
- line 63: `脚手架 怎么规定` expected `CJJ2` rank=None results=10 error=
- line 64: `脚手架` expected `CJJ2` rank=None results=10 error=
- line 65: `脚手架 施工要求` expected `CJJ2` rank=None results=10 error=
- line 66: `脚手架 验收标准` expected `CJJ2` rank=None results=1 error=
- line 67: `脚手架 质量要求` expected `CJJ2` rank=None results=10 error=
- line 68: `脚手架 设计要求` expected `CJJ2` rank=None results=10 error=
- line 69: `脚手架 规范` expected `CJJ2` rank=None results=3 error=
- line 80: `条文说明` expected `GB12523` rank=None results=10 error=
- line 81: `条文说明 怎么规定` expected `GB12523` rank=None results=10 error=
- line 82: `条文说明` expected `GB12523` rank=None results=10 error=
- line 83: `条文说明 施工要求` expected `GB12523` rank=None results=10 error=
- line 84: `条文说明 验收标准` expected `GB12523` rank=None results=0 error=
- line 85: `条文说明 质量要求` expected `GB12523` rank=None results=10 error=
- line 86: `条文说明 设计要求` expected `GB12523` rank=None results=10 error=
- line 87: `条文说明 规范` expected `GB12523` rank=None results=0 error=
- line 98: `钢筋保护层厚度` expected `GB1499.1` rank=None results=5 error=
- line 99: `钢筋保护层厚度 怎么规定` expected `GB1499.1` rank=None results=5 error=
- line 100: `钢筋保护层厚度` expected `GB1499.1` rank=None results=5 error=
