# -*- coding: utf-8 -*-
"""LLM 语义预判 — SiliconFlow API
引擎失败(needs_ai=True)时调用，返回 ai_hint 重跑引擎"""

import os, json, re, ssl as _sl
_SSL_CTX = _sl.create_default_context()
_SSL_CTX.maximum_version = _sl.TLSVersion.TLSv1_2  # SiliconFlow TLSv1.3 POST 兼容

from urllib import request, error

ENDPOINT = "https://api.siliconflow.cn/v1/chat/completions"
MODEL = "Qwen/Qwen2.5-32B-Instruct"

def _get_api_key():
    return os.environ.get("SILICONFLOW_API_KEY")

def call_llm_for_hint(para_text, code, clause, claimed, suggestion=""):
    """调用 LLM 分析上下文，返回结构化 ai_hint"""
    api_key = _get_api_key()
    if not api_key:
        return None

    prompt = f"""你是施工规范专家。以下施工方案引用需要核查，搜索引擎未找到匹配。

段落内容: {para_text[:400]}
方案引用: {code} {clause}
声称数值: {claimed}
引擎诊断: {suggestion}

请分析这段描述的是什么施工工艺，应该引用哪部规范的哪个条款。
返回纯JSON（不要markdown代码块）:
{{
  "topic": "这段描述的施工工艺",
  "search_terms": "最优搜索关键词(≤6字)",
  "expected_standards": ["规范编号1", "规范编号2"],
  "expected_clause": "最可能的正确条款号"
}}"""

    try:
        req = request.Request(ENDPOINT, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        body = json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 300,
        }).encode("utf-8")
        resp = request.urlopen(req, body, timeout=30, context=_SSL_CTX)
        data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        # 提取JSON
        m = re.search(r'\{[^{}]*"topic"[^{}]*\}', content, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"raw": content}
    except error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    key = _get_api_key()
    if not key:
        print("未配置: export SILICONFLOW_API_KEY=your-key")
        sys.exit(1)
    print(f"Key: {key[:8]}...")
    # 轻量测试
    hint = call_llm_for_hint(
        "混凝土浇筑完毕后12h内加以覆盖保湿养护时间不应少于7d",
        "GB50204", "7.4.7", "少于7d",
        "条款7.4.7不存在")
    print(json.dumps(hint, ensure_ascii=False, indent=2))
