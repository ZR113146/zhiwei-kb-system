# -*- coding: utf-8 -*-
"""Generate a current-state report for Zhiwei KB."""

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_CORE = os.path.join(ROOT, "kb_core")
PIPELINE = os.path.join(ROOT, "pipeline")
for path in (KB_CORE, PIPELINE, ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from kb_resolver_core import KBResolver, KB_JSON_DIR, KB_MD_DIR, SEARCH_INDEX  # noqa: E402
from standard_status import coverage, load_standard_status  # noqa: E402


def count_json_list(path):
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        if "entries" in data and isinstance(data["entries"], list):
            return len(data["entries"])
        if "images" in data and isinstance(data["images"], list):
            return len(data["images"])
        return len(data)
    return 0


def file_size(path):
    return os.path.getsize(path) if os.path.exists(path) else 0


def collect_state():
    kb = KBResolver()
    stats = kb.stats()
    vector_dir = os.path.join(ROOT, "data", "vectordb")
    vector_faiss = os.path.join(vector_dir, "vectors.faiss")
    vector_meta = os.path.join(vector_dir, "metadata.json")
    image_index = os.path.join(KB_JSON_DIR, "kb_image_index.json")
    ppr_graph = os.path.join(KB_JSON_DIR, "kb_ppr_graph.json")
    status_data = load_standard_status(KB_JSON_DIR)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": ROOT,
        "stats": stats,
        "paths": {
            "kb_md": KB_MD_DIR,
            "kb_json": KB_JSON_DIR,
            "search_index": SEARCH_INDEX,
            "vector_faiss": vector_faiss,
            "vector_metadata": vector_meta,
            "image_index": image_index,
            "ppr_graph": ppr_graph,
        },
        "artifacts": {
            "search_index_bytes": file_size(SEARCH_INDEX),
            "vector_faiss_bytes": file_size(vector_faiss),
            "vector_metadata_entries": count_json_list(vector_meta),
            "image_index_entries": count_json_list(image_index),
            "ppr_graph_bytes": file_size(ppr_graph),
        },
        "standard_status_coverage": coverage(status_data),
        "entrypoints": {
            "kb_loader.search": "hybrid search facade",
            "kb_loader.read_clause": "plain text clause reader",
            "kb_loader.status": "KBResolver.stats facade",
            "kb_loader.search_vector": "FAISS vector search facade",
        },
        "risk_areas": [
            "Search ranking has several heuristic weights and thresholds.",
            "PPR and vector boost are optional recall/ranking paths and need regression checks.",
            "Clause extraction depends on heading/index quality and can return unknown type.",
            "Version status starts as generated metadata and requires domain review.",
            "Pipeline rebuild touches search indexes and must keep kb_quality baselines stable.",
        ],
    }


def write_markdown(state, output_path):
    stats = state["stats"]
    lines = [
        "# Zhiwei KB Current State",
        "",
        f"Generated: {state['generated_at']}",
        f"Root: `{state['root']}`",
        "",
        "## Coverage",
        "",
        f"- Standards in index: {stats.get('standards_in_index', 0)}",
        f"- Indexed clauses: {stats.get('indexed_clauses', 0)}",
        f"- Code mapped: {stats.get('code_mapped', 0)}",
        f"- MD files: {stats.get('md_files', 0)}",
        f"- MD files with codes: {stats.get('md_with_codes', 0)}",
        f"- Vector metadata entries: {state['artifacts']['vector_metadata_entries']}",
        f"- Image index entries: {state['artifacts']['image_index_entries']}",
        "",
        "## Standard Status",
        "",
        f"- Records: {state['standard_status_coverage'].get('records', 0)}",
        f"- Known status: {state['standard_status_coverage'].get('known_status', 0)}",
        f"- Unknown status: {state['standard_status_coverage'].get('unknown_status', 0)}",
        f"- Coverage ratio: {state['standard_status_coverage'].get('coverage_ratio', 0)}",
        "",
        "## Query Flow",
        "",
        "1. `kb_loader.search()` calls `KBResolver.search()` with configured vector weight.",
        "2. `KBResolver.search()` checks normalized query-result cache.",
        "3. Exact filename/title and direct clause/parameter lookups return early when possible.",
        "4. Code, standard-name, and bool-filter queries use legacy keyword/BM25 search.",
        "5. Natural-language technical queries merge legacy recall, PPR discovery, and optional vector boost.",
        "6. Results are scored, deduplicated, annotated, cached, and returned.",
        "",
        "## Ingestion Flow",
        "",
        "1. Phase A: deduplicate, precheck, and split large PDFs.",
        "2. Phase B: run MinerU extraction.",
        "3. Phase C: import MD/JSON and rebuild indexes.",
        "4. Phase D: run verification, integrity checks, cleanup, and archive.",
        "",
        "## Risk Areas",
        "",
    ]
    lines.extend(f"- {item}" for item in state["risk_areas"])
    lines.extend(["", "## Key Paths", ""])
    for key, path in state["paths"].items():
        lines.append(f"- {key}: `{path}`")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Write current KB state reports")
    parser.add_argument("--json", default=os.path.join(ROOT, "docs", "kb_current_state.json"))
    parser.add_argument("--md", default=os.path.join(ROOT, "docs", "kb_current_state.md"))
    args = parser.parse_args()
    state = collect_state()
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    write_markdown(state, args.md)
    print(json.dumps({"json": args.json, "md": args.md, "stats": state["stats"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
