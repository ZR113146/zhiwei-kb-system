#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KB enhancer: apply dynamic KB audit notes and citation suggestions to a docx.

The enhancer is intentionally conservative: it appends yellow KB review notes
instead of replacing source text. Citation facts come from kb_auditor, which in
turn uses the unified retrieval workflow and support_guard diagnostics.
"""

import argparse
import os
import sys

from docx import Document

from kb_core.kb import KB, extract_code as _extract_code  # noqa: E402
from _utils import backup_docx as backup  # noqa: E402
from _docx_notes import yellow_append as _yellow_append, paragraph_by_index as _paragraph_by_index  # noqa: E402


def _audit_note(entry):
    resolution = entry.get('resolution') or {}
    suggestion = resolution.get('suggestion') or '需人工复核条款与原文是否一致'
    clause = resolution.get('clause') or entry.get('clause_ref') or ''
    source = resolution.get('source') or entry.get('code') or ''
    status = resolution.get('audit_status') or ''
    status_note = f'; audit={status}' if status and status != 'unknown' else ''
    return f' [KB校验: {source} {clause} {suggestion}{status_note}]'


def _citation_note(result):
    code = _extract_code(result.get('file', '')) or result.get('code', '') or result.get('standard_code', '')
    heading = result.get('heading', '')
    review = result.get('suggestion_review') or result.get('support_action', '')
    review_note = f'; {review}' if review and review != 'use_as_evidence' else ''
    if code and heading:
        return f' [L1:KB] 建议引用 {code} {heading[:60]}{review_note}'
    if heading:
        return f' [L1:KB] 建议引用 {heading[:70]}{review_note}'
    return ''


def enhance_docx(docx_path, output_path=None, max_citation_suggestions=20):
    """Enhance a document with KB audit notes and guarded citation suggestions."""
    if output_path is None:
        output_path = docx_path.replace('.docx', '_KB增强.docx')

    bak = backup(docx_path)
    print(f'Backup: {bak}')

    kb = KB()
    doc = Document(docx_path)
    stats = {
        'clauses_corrected': 0,
        'citations_added': 0,
        'review_notes': 0,
    }

    from kb_auditor import audit_report, suggest_citations

    _lines, audit_entries = audit_report(docx_path, kb=kb)
    for entry in audit_entries:
        resolution = entry.get('resolution') or {}
        if resolution.get('in_clause'):
            continue
        paragraph = _paragraph_by_index(doc, int(entry.get('para', -1)))
        if paragraph is None:
            continue
        note = _audit_note(entry)
        if note in paragraph.text:
            continue
        _yellow_append(paragraph, note)
        stats['clauses_corrected'] += 1
        stats['review_notes'] += 1
        print(f'  [AUDIT] P{entry.get("para")}: {note[:90]}...')

    added_suggestions = 0
    for para_idx, _text, results in suggest_citations(docx_path, kb=kb, max_paras=max_citation_suggestions):
        if added_suggestions >= max_citation_suggestions:
            break
        paragraph = _paragraph_by_index(doc, int(para_idx))
        if paragraph is None or not results:
            continue
        preferred = next((item for item in results if item.get('support_action') == 'use_as_evidence'), results[0])
        note = _citation_note(preferred)
        if not note or note in paragraph.text:
            continue
        _yellow_append(paragraph, note)
        stats['citations_added'] += 1
        added_suggestions += 1
        print(f'  [CITE] P{para_idx}: {note[:90]}...')

    doc.save(output_path)
    print(f'\n{"=" * 60}')
    print(f'KB 增强完成: {output_path}')
    print(f'  条款引用校验: {stats["clauses_corrected"]}')
    print(f'  KB引用补充:   {stats["citations_added"]}')
    print(f'  复核备注:     {stats["review_notes"]}')
    print(f'  总计修改:     {sum(stats.values())}')
    print(f'{"=" * 60}')
    return output_path, stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='KB Enhancer — 用统一检索工作流增强文档, 黄色背景标记修改')
    parser.add_argument('docx', help='Path to docx file')
    parser.add_argument('--output', '-o', help='Output path (default: *_KB增强.docx)')
    parser.add_argument('--max-citation-suggestions', type=int, default=20)
    args = parser.parse_args()

    enhance_docx(args.docx, args.output, max_citation_suggestions=args.max_citation_suggestions)
