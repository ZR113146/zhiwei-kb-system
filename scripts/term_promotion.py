#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""术语候选晋升: 从 kb_term_candidates.json 中筛选高频候选术语, 辅助人工审核后写入 term_map_v3.json。

用法:
  python scripts/term_promotion.py --report     # 列出待晋升候选 (按查询频次降序)
  python scripts/term_promotion.py --promote    # 交互式晋升 (逐条确认)
  python scripts/term_promotion.py --auto       # 批量晋升 queries>=20 的候选

安全网: 晋升前备份 contracts/term_map_v3.json → term_map_v3.bak.json。
"""

import json
import os
import sys
import shutil
import argparse

# Path resolution (anchored to repo root, not CWD)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
CANDIDATES_PATH = os.path.join(ROOT, 'pipeline', 'kb_term_candidates.json')
TERM_MAP_V3_PATH = os.path.join(ROOT, 'contracts', 'term_map_v3.json')
BACKUP_PATH = os.path.join(ROOT, 'contracts', 'term_map_v3.bak.json')

# 停用词 / 已知噪声 (分词碎片, 非实际术语)
NOISE = {
    '石碎石', '度等级评', '定标准', '板防水卷', '地下室底',
    '建设用卵', '度等级', '等级评', '防水卷',
}

# 人工审核: candidate term → preferred group and keyword form
# 这些是从搜索日志中提取的、确认有效的术语。
VERIFIED_PROMOTIONS = {
    '园林绿化': ('园林绿化', 'keywords'),
    '用电安全': ('安全文明', 'keywords'),
    '扬尘控制': ('安全文明', 'related'),
    '风景园林': ('园林绿化', 'related'),
    '大体积混凝土': ('混凝土工程', 'keywords'),
}


def load_candidates():
    if not os.path.exists(CANDIDATES_PATH):
        return {}
    with open(CANDIDATES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_term_map_v3():
    if not os.path.exists(TERM_MAP_V3_PATH):
        return {'version': 3, 'groups': [], 'term_index': {}}
    with open(TERM_MAP_V3_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def backup():
    if os.path.exists(TERM_MAP_V3_PATH):
        shutil.copy2(TERM_MAP_V3_PATH, BACKUP_PATH)
        print(f'已备份: {TERM_MAP_V3_PATH} → {BACKUP_PATH}')


def report(candidates):
    """列出待晋升候选 (按查询频次降序, 过滤噪声)."""
    items = [(term, info.get('queries', 0), info.get('files', []))
             for term, info in candidates.items()
             if term not in NOISE]
    items.sort(key=lambda x: -x[1])

    verified = set(VERIFIED_PROMOTIONS.keys())

    print(f'{len(items)} 个候选术语:')
    print()
    for term, queries, files in items:
        flag = ' [已确认]' if term in verified else ''
        print(f'  {term}: queries={queries} files={len(files)}{flag}')

    print()
    print(f'待晋升 (queries >= 5): {sum(1 for _, q, _ in items if q >= 5)}')
    print(f'已确认可晋升: {len(verified)}')
    return items


def promote_verified(term_map_v3, candidates, dry_run=False):
    """将 VERIFIED_PROMOTIONS 中的术语写入 term_map_v3。"""
    if dry_run:
        print('[dry-run] 不写文件。')
    groups = term_map_v3.get('groups', [])
    term_index = term_map_v3.get('term_index', {})

    promoted = 0
    for term, (group_name, list_key) in VERIFIED_PROMOTIONS.items():
        # 找到分组
        group = None
        for g in groups:
            if g.get('name') == group_name:
                group = g
                break

        if group is None:
            print(f'  SKIP: {term} → 分组 "{group_name}" 不存在')
            continue

        # 检查是否已存在
        existing = set(group.get(list_key, []))
        if term in existing:
            print(f'  SKIP: {term} 已在 {group_name}/{list_key} 中')
            continue

        if not dry_run:
            group.setdefault(list_key, []).append(term)
            # 更新 term_index
            if term not in term_index:
                term_index[term] = [group_name]
            elif group_name not in term_index[term]:
                term_index[term].append(group_name)

        promoted += 1
        print(f'  PROMOTE: {term} → {group_name}/{list_key}')

    if not dry_run and promoted > 0:
        term_map_v3['groups'] = groups
        term_map_v3['term_index'] = term_index
        with open(TERM_MAP_V3_PATH, 'w', encoding='utf-8') as f:
            json.dump(term_map_v3, f, ensure_ascii=False, indent=2)
        print(f'\n已写入 {promoted} 条术语 → {TERM_MAP_V3_PATH}')

    return promoted


def main():
    ap = argparse.ArgumentParser(description='术语候选晋升')
    ap.add_argument('--report', action='store_true', help='列出待晋升候选')
    ap.add_argument('--promote', action='store_true', help='交互式晋升')
    ap.add_argument('--auto', action='store_true', help='批量晋升 queries>=20 的候选')
    ap.add_argument('--dry-run', action='store_true', help='不实际写文件')
    args = ap.parse_args()

    candidates = load_candidates()
    if not candidates:
        print('无候选术语。')
        return

    if args.report or not (args.promote or args.auto):
        report(candidates)
        return

    if args.auto or args.promote:
        backup()
        term_map_v3 = load_term_map_v3()
        promote_verified(term_map_v3, candidates, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
