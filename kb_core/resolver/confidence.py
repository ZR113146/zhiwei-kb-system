# -*- coding: utf-8 -*-
"""resolver.confidence: KBResolver 的 ConfidenceMixin 方法组 (Step 3 拆分)。

从 kb_resolver_core 拆出, 方法体逐字保留。作为 mixin 被 KBResolver 继承,
共享 self 状态与跨组 self.method() 调用经 MRO 解析, 行为不变。
"""






class ConfidenceMixin:

    def _assign_confidence(self, results):
        for result in results or []:
            if not isinstance(result, dict):
                continue
            score = result.get('score', 0)
            result['confidence'] = 'high' if score >= 60 else ('mid' if score >= 20 else 'low')
        return results

    def _set_trace(self, results, trace):
        for result in results or []:
            if isinstance(result, dict):
                result['_trace'] = trace
        return results
