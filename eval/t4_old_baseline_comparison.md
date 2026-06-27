# KB Evaluation Comparison

## Metrics

- recall_at_5: 0.54 -> 0.56 delta=0.02 better
- mrr: 0.4712 -> 0.4912 delta=0.02 better
- ndcg_at_10: 0.4881 -> 0.5081 delta=0.02 better
- clause_hit_rate: 0.5 -> 0.5 delta=0.0 same
- no_result_rate: 0.08 -> 0.06 delta=-0.02 better
- stale_hit_rate: 0.04 -> 0.04 delta=0.0 same
- avg_elapsed_ms: 3071.86 -> 3501.43 delta=429.57 worse
- errors: 0 -> 0 delta=0 same

## Regressions


## Improvements

- `DB323700 现行吗` None -> 1 (new_hit)
- `DB323700 是否废止` None -> 1 (new_hit)
