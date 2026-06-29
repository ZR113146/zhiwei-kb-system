#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KB correction annotator driven by the unified citation audit workflow.

This module keeps the historical apply_corrections() entry point used by the
orchestrator, but no longer applies a hard-coded paragraph replacement table.
It appends conservative yellow correction suggestions derived from kb_auditor.
"""

import argparse
import os
import sys

from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kb_core'))
from kb_core.kb import KB  # noqa: E402
from _utils import backup_docx as backup  # noqa: E402
from _docx_notes import yellow_append as _yellow_append, paragraph_by_index as _paragraph_by_index  # noqa: E402


def _correction_note(entry):
    resolution = entry.get('resolution') or {}
    suggestion = resolution.get('suggestion') or '条款与表述未能由 KB 直接支撑，需人工复核'
    source = resolution.get('source') or entry.get('code') or ''
    clause = resolution.get('clause') or entry.get('clause_ref') or ''
    target = f'{source} {clause}'.strip()
    if target:
        return f' [KB修正建议: {target}；{suggestion}]'
    return f' [KB修正建议: {suggestion}]'


def _already_has_kb_note(paragraph, note):
    text = paragraph.text
    if note in text:
        return True
    return '[KB修正建议:' in text or '[KB校验:' in text


def apply_corrections(docx_path, output_path=None):
    """Append dynamic KB correction suggestions without replacing source text."""
    if output_path is None:
        output_path = docx_path.replace('.docx', '_条款修正.docx')

    bak = backup(docx_path)
    print(f'Backup: {bak}')

    kb = KB()
    doc = Document(docx_path)
    stats = {'fixed': 0, 'annotated': 0}

    from kb_auditor import audit_report

    _lines, entries = audit_report(docx_path, kb=kb)
    for entry in entries:
        resolution = entry.get('resolution') or {}
        if resolution.get('in_clause'):
            continue
        paragraph = _paragraph_by_index(doc, int(entry.get('para', -1)))
        if paragraph is None:
            continue
        note = _correction_note(entry)
        if _already_has_kb_note(paragraph, note):
            continue
        _yellow_append(paragraph, note)
        stats['annotated'] += 1
        print(f'  [NOTE] P{entry.get("para")}: {note[:90]}...')

    doc.save(output_path)
    print(f'\n{"=" * 60}')
    print(f'条款修正完成: {output_path}')
    print(f'  直接修正: {stats["fixed"]} 处')
    print(f'  追加注记: {stats["annotated"]} 处')
    print('  黄色背景 = KB修正建议')
    print(f'{"=" * 60}')
    return output_path, stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='KB条款修正 — 基于统一审计工作流追加修正建议')
    parser.add_argument('docx', help='Path to docx file')
    parser.add_argument('--output', '-o', help='Output path')
    args = parser.parse_args()
    apply_corrections(args.docx, args.output)
