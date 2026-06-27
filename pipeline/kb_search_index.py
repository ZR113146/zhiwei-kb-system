"""kb 知识库搜索索引 — 全量 + 增量 + 关键词搜索
用法: python kb_search_index.py --full | --incremental | "关键词"
"""
import os, re, json, sys
from datetime import datetime
# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
if _KB_DIR not in sys.path:
    sys.path.insert(0, _KB_DIR)
from kb import load_config
import changelog; changelog.record(__file__, sys.argv)

_cfg = load_config()
KB_DIR = _cfg['paths']['kb_md']
KB_JSON_DIR = _cfg['paths'].get('kb_json', os.path.join(os.path.dirname(KB_DIR), 'kb_json'))
MD_MANIFEST = _cfg['paths']['md_manifest']
INDEX_PATH = os.path.join(KB_JSON_DIR, 'kb_search_index.json')

# v6.17: 前导/目录/编制页噪音过滤
_FRONT_NOISE = {
    # 行政页
    '前言','目次','目录','总则','术语','符号','公告','通知',
    '修订说明','编制说明','条文说明','中华人民共和国','发布',
    '住房城乡建设部','关于发布','施行日期','主编单位','批准部门',
    '批准施行','发布公告','标准由','负责管理','归口','解释',
    # 编制/人员
    '编制人员','编制单位','编委','主编','参编','参加编制',
    '主要起草','主要审查','本标准主编','本标准参编',
    '起草人员','审查人员','参加单位','编制组','编写组',
    '技术负责人','技术审定','校核','审核人','审定人',
    '设计单位','勘察单位','施工单位','监理单位',
    '主要编写','主编单位','副主编',
    # 英文名
    'Standard for','Code for','Technical','General code',
}

def _is_front_heading(h):
    """判断是否为前导/目录/编制噪音标题"""
    # 目录条目: "章节名……页码" 或 "章节名 页码" 格式
    if re.search(r'……\s*\d{1,4}\s*$', h):
        return True
    # 目录条目变体: 长标题末尾紧跟页码 (如 "7 轴心受力构件…… 55")
    if re.search(r'[\s…]{2,}\d{2,4}\s*$', h):
        return True
    # 行政/编制噪音词
    h_stripped = h.replace(' ','').replace('\u3000','')
    for w in _FRONT_NOISE:
        if w in h_stripped:
            return True
    # 超长无条款号 → 公告/通知长句
    if len(h) > 60 and not re.search(r'\d+\.\d+|[IVXLCDM\u2160-\u217B]+\s', h):
        return True
    return False

def _find_boundaries(text):
    """Find key structural boundaries in the standard text (v6.18).

    条文说明边界检测策略:
    1. 标题含'条文说明' → commentary marker
    2. 标题含'用词说明' (如"本规程用词说明") → 跟在后面的是条文说明
    3. 引用标准名录 → 与条文说明之间的是过渡区
    """
    boundaries = {}
    body_start = 0
    toc = re.search(r'^#{1,3}\s+(?:目\s*次|目\s*录|Contents)\s*$', text, re.MULTILINE)
    scan_start = toc.end() if toc else 0
    for pat in (
        r'^#{1,3}\s+\d+\s+总\s*则\s*$',
        r'^#{1,3}\s+总\s*则\s*$',
        r'^#{1,3}\s+\d+\s+基本规定\s*$',
        r'^#{1,3}\s+基本规定\s*$',
    ):
        body = re.search(pat, text[scan_start:], re.MULTILINE)
        if body:
            body_start = scan_start + body.start()
            break
    boundaries['body_start'] = body_start
    # 条文说明 start — match headings containing 条文说明 or 用词说明
    for m in re.finditer(r'^#{1,3}\s+(.{0,80}?(?:条文说明|用词说明).*)$', text, re.MULTILINE):
        if body_start > 0 and m.start() < body_start:
            continue
        if _is_front_heading(m.group(1).strip()):
            continue
        boundaries['commentary_start'] = m.start()
        break
    # 附录 markers
    boundaries['appendix_starts'] = set()
    for m in re.finditer(r'^#{1,3}\s*附录\s', text, re.MULTILINE):
        boundaries['appendix_starts'].add(m.start())
    # 引用标准名录 (过渡区)
    for m in re.finditer(r'^#{1,3}\s*引用标准名录', text, re.MULTILINE):
        if body_start > 0 and m.start() < body_start:
            continue
        boundaries['ref_start'] = m.start()
        break
    return boundaries

def _section_type(heading, pos, boundaries):
    """Determine section type: normative > commentary > appendix > reference (v6.18)."""
    cs = boundaries.get('commentary_start')
    if cs is not None and pos >= cs:
        return 'commentary'
    if '附录' in heading:
        return 'appendix'
    rs = boundaries.get('ref_start')
    if rs is not None and pos >= rs:
        return 'reference'
    return 'normative'

def extract_sections(md_path):
    try: text = open(md_path, 'r', encoding='utf-8', errors='replace').read()
    except: return []
    boundaries = _find_boundaries(text)
    body_start = boundaries.get('body_start', 0)
    sections = []
    for m in re.finditer(r'^(#{1,3})\s+(.+)$', text, re.MULTILINE):
        h = m.group(2).strip()
        if body_start > 0 and m.start() < body_start:
            continue
        if not _is_front_heading(h):
            sections.append({
                'heading': h,
                'pos': m.start(),
                'type': _section_type(h, m.start(), boundaries)
            })
    for i, s in enumerate(sections):
        s['length'] = (sections[i+1]['pos'] - s['pos']) if i+1 < len(sections) else (len(text) - s['pos'])
    return [{'heading': s['heading'], 'pos': s['pos'], 'length': s['length'], 'type': s['type']} for s in sections]

def extract_sections_hybrid(md_path):
    """混合提取: MD #{1,3} + MinerU JSON 高置信度补充 → 合并去重"""
    sections = extract_sections(md_path)
    min_body_pos = min((s.get('pos', 0) for s in sections), default=0)

    # 尝试查找对应 JSON
    kb_json_dir = KB_JSON_DIR
    fname = os.path.basename(md_path)
    json_name = fname.replace('.md', '.json')
    json_path = os.path.join(kb_json_dir, json_name)

    if os.path.exists(json_path):
        try:
            from kb_heading_extractor import extract_high_conf_headings, merge_with_md
            json_heads = extract_high_conf_headings(json_path)
            if json_heads:
                md_text = open(md_path, 'r', encoding='utf-8', errors='replace').read()
                sections = merge_with_md(sections, json_heads, md_text)
                if min_body_pos > 0:
                    sections = [s for s in sections if s.get('pos', 0) >= min_body_pos]
        except Exception:
            pass

    # 重算所有 section 的 length
    if sections:
        try:
            text = open(md_path, 'r', encoding='utf-8', errors='replace').read()
            for i, s in enumerate(sections):
                end = sections[i+1]['pos'] if i+1 < len(sections) else len(text)
                s['length'] = max(1, end - s['pos'])
        except Exception:
            pass

    return sections

def build_full():
    md_files = sorted([f for f in os.listdir(KB_DIR) if f.endswith('.md')])
    print(f'扫描: {len(md_files)} 个MD')
    idx, total, json_total = {}, 0, 0
    for fname in md_files:
        s = extract_sections_hybrid(os.path.join(KB_DIR, fname))
        json_added = sum(1 for x in s if x.get('_source') == 'json_enriched')
        idx[fname] = s; total += len(s); json_total += json_added
    data = {'_meta': {'updated': datetime.now().isoformat(), 'total_files': len(md_files), 'total_sections': total, 'json_enriched': json_total}, 'index': idx}
    with open(INDEX_PATH, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'索引: {len(md_files)}文件 {total}章节 ({json_total}来自JSON补充)')

def build_incremental():
    if not os.path.exists(MD_MANIFEST): build_full(); return
    with open(MD_MANIFEST, 'r', encoding='utf-8') as f: manifest = json.load(f)
    existing = {}
    sections_before = 0
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            prev = json.load(f)
            existing = prev.get('index', {})
            sections_before = sum(len(v) for v in existing.values())
    new_count = 0
    for fname in sorted(os.listdir(KB_DIR)):
        if not fname.endswith('.md') or fname in existing: continue
        existing[fname] = extract_sections_hybrid(os.path.join(KB_DIR, fname))
        new_count += 1
    # 清理已删除的 MD 文件条目
    current_files = set(f for f in os.listdir(KB_DIR) if f.endswith('.md'))
    removed = [f for f in existing if f not in current_files]
    for f in removed:
        del existing[f]
    total_sections = sum(len(v) for v in existing.values())
    data = {'_meta': {'updated': datetime.now().isoformat(), 'total_files': len(existing), 'total_sections': total_sections}, 'index': existing}
    with open(INDEX_PATH, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'增量: +{new_count}文件 -{len(removed)}文件 +{total_sections - sections_before}章节\n总计: {len(existing)}文件 {total_sections}章节')

def search(query):
    if not os.path.exists(INDEX_PATH): print('索引不存在，先建索引'); return
    with open(INDEX_PATH, 'r', encoding='utf-8') as f: idx = json.load(f).get('index', {})
    keywords = query.split()
    results = []
    for fname, sections in idx.items():
        for sec in sections:
            score = sum(1 for kw in keywords if kw.lower() in sec['heading'].lower())
            if score > 0: results.append((fname, sec, score))
    results.sort(key=lambda x: x[2], reverse=True)
    if not results: print('无结果'); return
    print('='*60)
    for i, (fname, sec, score) in enumerate(results[:15]):
        try:
            text = open(os.path.join(KB_DIR, fname), 'r', encoding='utf-8', errors='replace').read()
            excerpt = text[sec['pos']:sec['pos']+sec['length']][:300]
        except: excerpt = '(无法读取)'
        print(f'\n[{i+1}] {fname}\n    章节: {sec["heading"]}\n    得分: {score}关键词\n{excerpt}')
        print('='*60)

if __name__ == '__main__':
    if len(sys.argv) < 2: print('用法: --full | --incremental | "关键词"'); sys.exit(1)
    if sys.argv[1] == '--full': build_full()
    elif sys.argv[1] == '--incremental': build_incremental()
    else: search(sys.argv[1])
