# -*- coding: utf-8 -*-
"""Golden query generator for KB evaluation."""

import argparse
import json
import os
import random
import re
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_CORE = os.path.join(ROOT, "kb_core")
if KB_CORE not in os.sys.path:
    os.sys.path.insert(0, KB_CORE)

from standard_status import extract_standard  # noqa: E402

DEFAULT_OUTPUT = os.path.join(ROOT, "eval", "golden_queries.jsonl")

QUERY_TEMPLATES = [
    ("standard_code", "{code} 现行吗"),
    ("standard_code", "{code} 第{clause}条"),
    ("standard_code", "{code} {name} 条文说明"),
    ("standard_name", "{name}"),
    ("standard_name", "{name} 适用范围"),
    ("clause", "{name} {clause}"),
    ("clause", "{name} 第{clause}条"),
    ("parameter", "{keyword}"),
    ("parameter", "{keyword} 怎么规定"),
    ("technical", "{keyword}"),
    ("technical", "{keyword} 施工要求"),
    ("technical", "{keyword} 验收标准"),
    ("technical", "{keyword} 质量要求"),
    ("technical", "{keyword} 设计要求"),
    ("technical", "{keyword} 规范"),
    ("version", "{name} 现行版本"),
    ("version", "{code} 是否废止"),
    ("comparison", "{name} 和 {alt_name} 区别"),
]

BASE_KEYWORDS = [
    "钢筋保护层厚度",
    "混凝土强度等级",
    "脚手架",
    "高处作业",
    "基坑支护",
    "防火间距",
    "屋面防水",
    "给排水",
    "电气安装",
    "绿色施工",
    "质量验收",
    "材料性能",
    "施工方案",
    "条文说明",
    "附录",
    "表格",
    "图片",
]

SPECIAL_CASES = [
    {"code": "GB50204-2015", "name": "混凝土结构工程施工质量验收规范", "clause": "5.3.2", "keyword": "钢筋保护层厚度", "alt_name": "混凝土结构工程施工规范"},
    {"code": "GB50016-2014", "name": "建筑设计防火规范", "clause": "5.5.17", "keyword": "防火间距", "alt_name": "建筑防火通用规范"},
    {"code": "JGJ59-2011", "name": "建筑施工安全检查标准", "clause": "3.0.3", "keyword": "安全检查", "alt_name": "建筑施工高处作业安全技术规范"},
    {"code": "GB50007-2011", "name": "建筑地基基础设计规范", "clause": "5.2.4", "keyword": "承载力", "alt_name": "建筑基坑支护技术规程"},
    {"code": "GB50300-2013", "name": "建筑工程施工质量验收统一标准", "clause": "3.0.1", "keyword": "质量验收", "alt_name": "建筑工程施工规范"},
    {"code": "JGJ80-2016", "name": "建筑施工高处作业安全技术规范", "clause": "5.1.2", "keyword": "高处作业", "alt_name": "建筑施工安全检查标准"},
    {"code": "GB50268-2008", "name": "给水排水管道工程施工及验收规范", "clause": "6.7.10", "keyword": "排水管道", "alt_name": "室外排水设计规范"},
    {"code": "GB50015-2019", "name": "建筑给水排水设计标准", "clause": "6.7.1", "keyword": "给排水", "alt_name": "建筑给水排水及采暖工程施工质量验收规范"},
]


def load_manifest():
    manifest_path = os.path.join(ROOT, "data", "kb_json", "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_seed_cases():
    manifest = load_manifest()
    cases = []
    seen = set()
    for raw_code, filename in sorted(manifest.get("standards", {}).items()):
        extracted = extract_standard(filename) or extract_standard(raw_code)
        if not extracted:
            continue
        code = extracted["standard_code"]
        name = extracted["standard_name"]
        if not code or code in seen:
            continue
        seen.add(code)
        clause = random.choice(["1.0.1", "3.0.1", "4.1.1", "5.1.1", "6.1.1"])
        keyword = random.choice(BASE_KEYWORDS)
        alt_name = name.replace("规范", "标准") if name else "相关标准"
        cases.append({"code": code, "name": name, "clause": clause, "keyword": keyword, "alt_name": alt_name})
        if len(cases) >= 32:
            break
    for case in SPECIAL_CASES:
        if case["code"] not in seen:
            cases.append(case)
            seen.add(case["code"])
    return cases


def normalize_query_type(kind):
    mapping = {
        "standard_code": "standard_code",
        "standard_name": "standard_name",
        "clause": "clause",
        "parameter": "parameter",
        "technical": "technical",
        "version": "version",
        "comparison": "comparison",
    }
    return mapping.get(kind, "technical")


def build_queries(seed_cases, target_size=100):
    records = []
    for case in seed_cases:
        for kind, template in QUERY_TEMPLATES:
            query = template.format(**case)
            records.append({
                "query": query,
                "query_type": normalize_query_type(kind),
                "expected_standard_code": case["code"],
                "expected_standard_name": case["name"],
                "expected_clause": case.get("clause", ""),
                "must_include": [case.get("keyword", "")],
                "must_not": ["废止" if kind != "version" else ""],
                "priority": 1 if kind in ("standard_code", "clause", "version") else 2,
                "notes": "generated_seed",
            })
            if len(records) >= target_size:
                return records
    return records


def write_jsonl(records, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for item in records:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Generate golden KB queries")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)
    records = build_queries(build_seed_cases(), target_size=args.size)
    write_jsonl(records, args.output)
    print(json.dumps({"output": args.output, "count": len(records)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
