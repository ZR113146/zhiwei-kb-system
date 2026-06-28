# -*- coding: utf-8 -*-
"""gap扫描: 程序检测方案缺陷,输出修复清单(不用AI)"""
import os, re, json, argparse, sys
from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kb_core'))
from kb import KB, normalize_code
import changelog; changelog.record(__file__, sys.argv)
from _utils import find_latest_docx

def _load_relevance_keywords():
    """Load project-type-specific keywords from project.json + project_type_map.json.
    Falls back to generic construction keywords if no project config exists."""
    try:
        ref_dir = os.path.dirname(__file__)
        try:
            from kb import load_config
            _paths = load_config().get('paths', {})
        except Exception:
            _paths = {}
        project_json = os.path.join(os.path.dirname(__file__), '..', 'content', 'project.json')
        keywords = set()

        if os.path.exists(project_json):
            with open(project_json, 'r', encoding='utf-8') as f:
                proj = json.load(f)
            ptypes = proj.get('project_types', [])
            if not ptypes:
                ptypes = ['\u56ed\u6797\u666f\u89c2']  # default fallback

            # Load category→keyword mapping from standard_tags
            tag_path = _paths.get('standard_tags', '') or os.path.join(ref_dir, 'standard_tags.json')
            cat_keywords = {}
            if os.path.exists(tag_path):
                with open(tag_path, 'r', encoding='utf-8') as f:
                    tags = json.load(f)
                for cat, desc in tags.get('_categories', {}).items():
                    kws = [k.strip() for k in desc.replace('\uff0c', ',').split(',')]
                    cat_keywords[cat] = kws

            # Load project type→categories from project_type_map
            pmap_path = _paths.get('project_type_map', '') or os.path.join(ref_dir, 'project_type_map.json')
            if os.path.exists(pmap_path):
                with open(pmap_path, 'r', encoding='utf-8') as f:
                    pmap = json.load(f)
                for ptype in ptypes:
                    info = pmap.get('mappings', {}).get(ptype, {})
                    for cat in info.get('categories', []):
                        for kw in cat_keywords.get(cat, []):
                            keywords.add(kw)
                    for cat in info.get('optional', []):
                        for kw in cat_keywords.get(cat, []):
                            keywords.add(kw)

        if not keywords:
            # Fallback: broad construction keywords
            keywords = {'\u5730\u57fa', '\u6df7\u51dd\u571f', '\u94a2\u7ed3\u6784', '\u780c\u4f53',
                       '\u94fa\u88c5', '\u7ed9\u6c34', '\u6392\u6c34', '\u56ed\u6797', '\u7535\u6c14',
                       '\u9053\u8def', '\u5b89\u5168', '\u8d28\u91cf', '\u9a8c\u6536', '\u566a\u58f0'}
        return list(keywords)
    except Exception as e:
        import sys as _sys
        import logging
        logging.warning(f'Keyword loading failed ({e}), using minimal fallback. '
                       'Run "python build_index.py --full" to rebuild keyword data.')
        return ['\u5730\u57fa', '\u6df7\u51dd\u571f', '\u94a2\u7ed3\u6784', '\u56ed\u6797', '\u7ed9\u6c34']

def scan_docx(docx_path):
    """扫描docx文档,输出gap清单"""
    doc = Document(docx_path)
    kb = KB()
    gaps = []
    all_text = []

    # 收集所有段落
    for i, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        if text:
            all_text.append((i, text))

    # 1. 引用完整性检查: 含控制性数值但缺规范引用
    numeric_pattern = re.compile(r'(?:[≥≤≧>]|不小于|不大于|不得超过|不应[大小低高])\s*\d+\.?\d*\s*(mm|cm|m|d|天|h|小时|kN|MPa|dB|%|‰)')
    citation_pattern = re.compile(r'(?:GB(?:/T)?|JGJ|CJJ|CECS|CJ/T|DB)\s*\d+')
    standard_refs = set()

    for i, text in all_text:
        # 收集已有引用
        for m in citation_pattern.finditer(text):
            standard_refs.add(m.group())
        # 检查控制性数值但缺引用（跳过列表项如"——"开头和纯"依据"表述）
        if numeric_pattern.search(text) and not citation_pattern.search(text):
            if not text.startswith('|') and not text.startswith('【') and not text.startswith('——'):
                # 跳过虽含数值但已有"依据"引用的（可能引用在前后句）
                if '依据' not in text and '符合' not in text:
                    gaps.append({
                        'type': 'citation_missing',
                        'paragraph': i,
                        'text': text[:150],
                        'severity': 'medium'
                    })

    # 2. 版本号校验 — 用 kb_resolver 统一查询
    known_refs = set()
    for i, text in all_text:
        for m in re.finditer(r'((?:GB\s*/?\s*T?|JGJ|CJJ|CECS|CJ\s*/?\s*T?)\s*\d+[\.-]\d+(?:-\d+)?)', text):
            known_refs.add(normalize_code(m.group()))

    # 动态加载项目类型关键词过滤（从 project.json 读取当前项目类型）
    relevance_keywords = _load_relevance_keywords()
    unused = kb.list_unused(known_refs, keyword_filter=relevance_keywords) if relevance_keywords else []
    for code in unused[:10]:
        gaps.append({
            'type': 'unused_standard',
            'paragraph': -1,
            'reference': code,
            'text': f'KB has standard {code} - consider citing',
            'severity': 'low'
        })

    # 3. 跨章数值冲突检测（要求紧接关键词+比较词+数值+单位的完整模式）
    key_values = {}
    patterns = {
        '养护时间': re.compile(r'养护(?:时间)?(?:不[得应][少低大于超]|≥|≧)?\s*(\d+)\s*[d天]'),
        '压实系数': re.compile(r'压实系数[λc]?\s*(?:不[得应][少低大于超]|≥|≧|≧)\s*([0-9.]+)'),
        '开挖深度': re.compile(r'(?:最大)?开挖深度(?:不[得应][超大于])?\s*(\d+\.?\d*)\s*[m米]'),
        '振动速度': re.compile(r'振动速度(?:不[得应][超大于]|控制在)?\s*(\d+\.?\d*)\s*mm/s'),
    }
    # Subject-disambiguation: extract noun before keyword to tell if values refer to different things
    _subject_re = re.compile(r'([\u4e00-\u9fff]{2,6})\s*(?:最大)?(?:养护时间|压实系数|开挖深度|振动速度)')
    for i, text in all_text:
        for key, pat in patterns.items():
            m = pat.search(text)
            if m:
                val = m.group(1)
                try:
                    fv = float(val)
                    if key == '养护时间' and (fv < 2 or fv > 30): continue
                    if key == '压实系数' and (fv < 0.5 or fv > 5): continue
                    if key == '开挖深度' and (fv < 0.5 or fv > 20): continue
                    if key == '振动速度' and (fv < 0.1 or fv > 100): continue
                except ValueError:
                    continue
                # Extract subject context (equipment/method/category)
                sm = _subject_re.search(text)
                subject = sm.group(1) if sm else ''
                if key not in key_values:
                    key_values[key] = []
                key_values[key].append((i, val, text[:100], subject))

    for key, vals in key_values.items():
        unique_vals = set(v[1] for v in vals)
        # 合并等效值：1.5=1500mm不算冲突
        normalized = set()
        for v in unique_vals:
            try:
                fv = float(v)
                # Use unit suffix rather than numeric threshold (fixes deep excavation false-positive)
                if key == '开挖深度':
                    unit_match = re.search(r'(?:开挖深度[^0-9]*\d+\.?\d*)\s*(mm|cm|m|米)', text)
                    if unit_match and unit_match.group(1) in ('mm',):
                        normalized.add(str(fv/1000))  # 1500mm → 1.5m
                    elif unit_match and unit_match.group(1) in ('cm',):
                        normalized.add(str(fv/100))   # 150cm → 1.5m
                    else:
                        normalized.add(str(fv))
                elif key == '养护时间' and fv > 60:
                    normalized.add(str(fv/24))  # hours → days
                else:
                    normalized.add(str(fv))
            except ValueError:
                normalized.add(v)
        if len(normalized) > 1:
            # Subject disambiguation: different subjects with same keyword → not a real conflict
            subjects = set(v[3] for v in vals if v[3])
            sev = 'low' if key == '养护时间' else 'high'
            if subjects and len(subjects) > 1:
                # Values from clearly different subjects (e.g. 设备伞1.3m vs EPS换填1.5m) → downgrade
                sev = 'low'
            gaps.append({
                'type': 'value_conflict',
                'key': key,
                'values': sorted(normalized),
                'locations': [f'P{v[0]}' for v in vals],
                'subjects': sorted(subjects) if subjects else [],
                'severity': sev
            })

    # 4. 占位符残留
    for i, text in all_text:
        if '【' in text and '】' in text:
            gaps.append({
                'type': 'placeholder_remaining',
                'paragraph': i,
                'text': text[:150],
                'severity': 'low'
            })

    return gaps

def print_report(gaps):
    """打印gap报告"""
    if not gaps:
        print('No gaps found.')
        return

    by_severity = {'high': [], 'medium': [], 'low': []}
    for g in gaps:
        by_severity[g['severity']].append(g)

    print(f'Total gaps: {len(gaps)} (high:{len(by_severity["high"])} medium:{len(by_severity["medium"])} low:{len(by_severity["low"])})\n')

    for sev in ['high', 'medium', 'low']:
        for g in by_severity[sev]:
            if g['type'] == 'citation_missing':
                print(f'  [{sev}] 缺引用: P{g["paragraph"]} | {g["text"]}')
            elif g['type'] == 'version_mismatch':
                print(f'  [{sev}] 版本不匹配: P{g["paragraph"]} | {g["reference"]}')
            elif g['type'] == 'value_conflict':
                print(f'  [{sev}] 数值冲突: {g["key"]} = {g["values"]} @ {g["locations"]}')
            elif g['type'] == 'placeholder_remaining':
                print(f'  [{sev}] 占位符残留: P{g["paragraph"]} | {g["text"]}')
            print()


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('docx', nargs='?', help='Path to docx file (optional with --find)')
    parser.add_argument('--find', action='store_true', help='Auto-find latest docx on Desktop')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    docx_path = args.docx
    if args.find or not docx_path:
        docx_path = find_latest_docx()
        if not docx_path:
            print('ERROR: No .docx found on Desktop. Specify path explicitly.')
            sys.exit(1)
        print(f'Found: {docx_path}\n')

    if not os.path.exists(docx_path):
        print(f'ERROR: File not found: {docx_path}')
        sys.exit(1)

    gaps = scan_docx(docx_path)
    if args.json:
        print(json.dumps(gaps, ensure_ascii=False, indent=2))
    else:
        print_report(gaps)
