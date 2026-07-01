"""条款编号索引 — 从搜索索引 section 中提取条款编号→位置映射
输出: data/kb_json/kb_clause_index.json
用法: python kb_clause_index.py
"""
import json, os, re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from kb_core.code_norm import extract_standard  # noqa: E402

KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
SEARCH_INDEX = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_search_index.json')
OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_clause_index.json')

def build():
    with open(SEARCH_INDEX, 'r', encoding='utf-8') as f:
        si = json.load(f)

    clause_pat = re.compile(r'^(\d+(?:\.\d+)*)\s')
    roman_pat = re.compile(r'^([IVXLCDM\u2160-\u217B]+)\s')
    chinese_pat = re.compile(r'^第([一二三四五六七八九十百千\d]+)条')
    _is_roman = re.compile(r'^[IVXLCDM\u2160-\u217B]+$')

    idx = {}
    total_clauses = 0

    for fname, secs in si['index'].items():
        clauses = []
        last_arabic = None  # track nearest non-Roman clause for parent inference

        # Extract standard code from filename —— 委托 code_norm 唯一真源
        # (旧内联正则 [\sT/_]? 单分隔符解析不了入库下划线 GB_T 形式, 致
        #  lookup 双 key: GB_T类回退文件名、GB类带年份。现统一为规范形 GBT50720。
        #  抽不出码时保留 fname[:30] 兜底, 不丢该文件条款。)
        _si = extract_standard(fname)
        std_code = _si['standard_code'] if _si and _si['standard_code'] else fname[:30]

        for i, s in enumerate(secs):
            h = s.get('heading', '')
            pos = s.get('pos', 0)
            length = s.get('length', 0)
            stype = s.get('type', 'normative')

            # Try Arabic numeral pattern: "5.3.2 标题"
            m = clause_pat.match(h)
            if m:
                number = m.group(1)
                title = h[m.end():].strip()
            else:
                # Try Roman numeral pattern: "IV 一般规定"
                m_roman = roman_pat.match(h)
                if m_roman:
                    number = m_roman.group(1)
                    title = h[m_roman.end():].strip()
                else:
                    # Try Chinese pattern: "第二条 标题"
                    m2 = chinese_pat.match(h)
                    if m2:
                        number = '第' + m2.group(1) + '条'
                        title = h[m2.end():].strip()
                    else:
                        continue  # Not a numbered clause

            # Determine parent
            parts = number.split('.') if '.' in number else [number]
            if len(parts) > 1:
                parent = '.'.join(parts[:-1])
            elif _is_roman.match(number) and last_arabic:
                parent = last_arabic
            else:
                parent = None

            # Track last non-Roman clause for Roman numeral parent inference
            if not _is_roman.match(number):
                last_arabic = number

            clauses.append({
                'number': number,
                'title': title,
                'pos': pos,
                'length': length,
                'parent': parent,
                'type': stype
            })
            total_clauses += 1

        if clauses:
            idx[fname] = {
                'std_code': std_code,
                'clauses': clauses
            }

    output = {
        '_meta': {
            'total_files': len(idx),
            'total_clauses': total_clauses,
            'source': 'kb_search_index.json'
        },
        'index': idx,
        # Inverted lookup: clause_number → (fname, pos, length)
        'lookup': {}
    }

    # Build inverted lookup for exact clause queries
    # 类型优先级: 同一 (std:number) 键若 normative 与 commentary 并存 (加了叶子条款分段后
    # 正文与条文说明的同号条款都成 section), normative 不被 commentary/appendix 覆盖。
    _TYPE_PRIO = {'normative': 0, 'commentary': 1, 'appendix': 2, 'reference': 3}
    for fname, data in idx.items():
        for c in data['clauses']:
            key = '%s:%s' % (data['std_code'], c['number'])
            existing = output['lookup'].get(key)
            if existing and _TYPE_PRIO.get(existing.get('type', 'normative'), 0) <= _TYPE_PRIO.get(c.get('type', 'normative'), 0):
                continue  # 保留更高/同优先级的既有条目 (normative 胜 commentary)
            output['lookup'][key] = {
                'fname': fname,
                'number': c['number'],
                'title': c['title'],
                'pos': c['pos'],
                'length': c['length'],
                'type': c['type']
            }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    print('Clause index: %d files, %d clauses, %.1fKB' % (
        len(idx), total_clauses, os.path.getsize(OUTPUT)/1024))

if __name__ == '__main__':
    build()
