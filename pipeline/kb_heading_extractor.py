# -*- coding: utf-8 -*-
"""知微 KB 标题提取引擎 v2.0
混合策略: MD #{1,3} 为主 + MinerU JSON 高置信度补充 → 合并去重

核心思路:
  - MD 正则提取是已验证的主力 (精准但召回有限)
  - JSON 评分引擎只输出 score >= 50 的高置信度补充标题
  - 合并时按 pos 偏移去重 (10 char 内视为同一标题)
  - 结果被 kb_search_index.py 调用以替代纯 MD 提取

8 信号评分 (用于 JSON 块):
  1. 字号差 (bbox height ratio)      max +30
  2. 缩进差 (x0 offset)              max +15
  3. 短行 (text < 36 chars)          max +15
  4. 编号匹配 (numbering regex)      max +50 (>55 chars → 降为条款正文)
  5. MinerU text_level               max +40
  6. 布局类型 (title/list)           max +25
  7. 页位 (top-of-page y0)           max +15
  8. 上下文 (短→长 neighbor ratio)   max +12

仅 score >= 50 输出为标题补充。
"""
import json, os, re, sys
from collections import Counter

# ── 噪音词 ──
_FRONT_NOISE = {
    '前言','目次','目录','总则','术语','符号','公告','通知',
    '修订说明','编制说明','条文说明','中华人民共和国','发布',
    '住房城乡建设部','关于发布','施行日期','主编单位','批准部门',
    '批准施行','发布公告','标准由','负责管理','归口','解释',
    '编制人员','编制单位','编委','主编','参编','参加编制',
    '主要起草','主要审查','本标准主编','本标准参编',
    '起草人员','审查人员','参加单位','编制组','编写组',
    '技术负责人','技术审定','校核','审核人','审定人',
    '设计单位','勘察单位','施工单位','监理单位',
    '主要编写','主编单位','副主编','Standard for','Code for','Technical','General code',
}

_NOISE_PATTERNS = [
    re.compile(r'\d{4}[-年]\d{1,2}[-月]\d{1,2}'),
    re.compile(r'^\d{4}\s*年\s*\d{1,2}\s*月'),
    re.compile(r'统一书号|ISBN|定价|印数|印张|开本|字数|版权所有'),
    re.compile(r'^第\s*\d+\s*号$'),
    re.compile(r'^\d+[-–—]\d+$'),
    re.compile(r'^\d+年\d+月第\d+版'),
]

NUM_PATTERNS = [
    (re.compile(r'^第[一二三四五六七八九十百千\d]+章'), 1),
    (re.compile(r'^第[一二三四五六七八九十百千\d]+节'), 2),
    (re.compile(r'^[IVXLCDM\u2160-\u217B]+\s+\S'), 2),
    (re.compile(r'^\d+\.\d+\.\d+\.\d+'), 4),
    (re.compile(r'^\d+\.\d+\.\d+'), 3),
    (re.compile(r'^\d+\.\d+'), 2),
    (re.compile(r'^[（(][一二三四五六七八九十]+[）)]'), 3),
    (re.compile(r'^[一二三四五六七八九十]+[、．.]\s*\S'), 3),
]
# 纯数字章标题: "3 基本规定" 格式, text_len <= 12, 不含条款动词
_CHAPTER_DIGIT_PAT = re.compile(r'^(\d+)\s+(\S)')
_CHAPTER_MAX_LEN = 12
_CLAUSE_VERBS = re.compile(r'[应宜可不得不应必须严禁禁止]')

CLAUSE_BODY_LEN = 22  # 编号块超此长度 → 条款正文
_CLAUSE_MARKERS = [
    re.compile(r'应符合下列规定[：:]'),
    re.compile(r'应符合下列要求[：:]'),
    re.compile(r'应按下列.*执行[：:]'),
    re.compile(r'应[符按].*规定[：:]'),
    re.compile(r'[：:]\s*$'),
]
# TOC/目录条目检测 (标题后跟页码)
_TOC_PATTERNS = [
    re.compile(r'……\s*[（(]?\d{1,4}[）)]?\s*$'),
    re.compile(r'[\s…]{2,}\d{2,4}\s*$'),
    re.compile(r'[（(]\d{1,4}[）)]\s*$'),
]
SKIP_TYPES = {'image', 'table', 'page_number', 'header', 'footer', 'equation'}


def _is_noise(text):
    t = text.replace(' ', '').replace('\u3000', '')
    for w in _FRONT_NOISE:
        if w in t:
            return True
    for pat in _NOISE_PATTERNS:
        if pat.search(text):
            return True
    return False


def load_json_items(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    items = []
    for it in raw:
        tp = it.get('type', 'text')
        if tp in SKIP_TYPES:
            continue
        text = (it.get('text') or '').strip()
        if not text or len(text) < 3:
            continue
        bbox = it.get('bbox', [0, 0, 0, 0])
        items.append({
            'text': text, 'bbox': bbox,
            'page': it.get('page_idx', 0),
            'text_level': it.get('text_level'),
            'type': tp,
            'height': bbox[3] - bbox[1],
            'x0': bbox[0], 'y0': bbox[1],
        })
    return items


def compute_baselines(items):
    heights = [it['height'] for it in items]
    x0s = [it['x0'] for it in items]
    if not heights:
        return 12, 50
    body_h = Counter(round(h) for h in heights).most_common(1)[0][0]
    body_x0 = Counter(round(x) for x in x0s).most_common(1)[0][0]
    return body_h, body_x0


def extract_high_conf_headings(json_path, min_score=65):
    """从 MinerU JSON 提取高置信度标题 (score >= min_score)

    Returns: list of {'heading', 'level', 'score', 'number', 'pos'}
    其中 pos 为重建全文本中的字符偏移量
    """
    items = load_json_items(json_path)
    body_h, body_x0 = compute_baselines(items)
    body_h = max(body_h, 1)

    # ── 检测 术语/定义 章节 ──
    in_glossary = False
    glossary_start_page = -1
    glossary_start_idx = -1

    # 先扫描找"术语"章节标记
    for idx, it in enumerate(items):
        t = it['text'].strip()
        if re.match(r'^[\d.]*\s*术语\s*$', t) or t == '术语':
            in_glossary = True
            glossary_start_page = it['page']
            glossary_start_idx = idx
            break

    # 术语章节结束标记: 下一个编号>=3 的章节
    glossary_end_idx = 999999
    if in_glossary:
        for idx in range(glossary_start_idx + 1, len(items)):
            t = items[idx]['text'].strip()
            m = re.match(r'^(\d+)\s', t)
            if m and int(m.group(1)) >= 3:
                glossary_end_idx = idx
                break

    # ── 重建全文本 (含位置映射) ──
    full_text = ''
    pos_map = []  # [(start, end, item_idx)]
    for i, it in enumerate(items):
        start = len(full_text)
        full_text += it['text'] + '\n\n'
        pos_map.append((start, len(full_text), i))

    # ── 逐块评分 ──
    headings = []
    for idx, it in enumerate(items):
        text_clean = it['text'].strip()
        text_len = len(text_clean)

        # 噪音
        if _is_noise(text_clean):
            continue

        # TOC/目录条目
        is_toc = False
        for tp in _TOC_PATTERNS:
            if tp.search(text_clean):
                is_toc = True
                break
        if is_toc:
            continue

        # 术语章节内的编号短词 → 跳过
        if in_glossary and glossary_start_idx <= idx < glossary_end_idx:
            if re.match(r'^\d+\.\d+\.\d+', text_clean) and text_len < 80:
                continue

        score = 0
        h_ratio = it['height'] / body_h

        # S1: 字号差
        if h_ratio > 1.40:       score += 30
        elif h_ratio > 1.20:     score += 22
        elif h_ratio > 1.10:     score += 14
        elif h_ratio > 1.05:     score += 6

        # S2: 缩进差
        x0_diff = body_x0 - it['x0']
        if x0_diff > 20:         score += 15
        elif x0_diff > 12:       score += 10
        elif x0_diff > 6:        score += 5
        elif x0_diff < -8:       score -= 8

        # S3: 短行
        if text_len < 10:        score += 15
        elif text_len < 22:      score += 10
        elif text_len < 36:      score += 5
        elif text_len > 120:     score -= 12

        # S4: 编号匹配
        level_override = None
        is_clause_body = False
        matched = False
        for pat, lvl in NUM_PATTERNS:
            if pat.match(text_clean):
                matched = True
                if lvl in (2, 3, 4) and text_len > CLAUSE_BODY_LEN:
                    score += 15
                    is_clause_body = True
                else:
                    score += 50
                    level_override = lvl
                break

        # 纯数字章标题: "3 基本规定" (数字+空格+短标题, 非条款动词)
        if not matched and not is_clause_body:
            cm = _CHAPTER_DIGIT_PAT.match(text_clean)
            if cm and text_len <= _CHAPTER_MAX_LEN and not _CLAUSE_VERBS.search(text_clean):
                score += 45
                level_override = 1

        # 条款正文特征检测 (引导列表、冒号结尾)
        if not is_clause_body:
            for cm in _CLAUSE_MARKERS:
                if cm.search(text_clean):
                    is_clause_body = True
                    score -= 30
                    break

        if is_clause_body:
            continue

        # S5: MinerU text_level (降权 — 误标较多)
        tl = it.get('text_level')
        if tl == 1:              score += 25
        elif tl == 2:            score += 18
        elif tl == 3:            score += 10

        # S6: 布局类型
        tp = it.get('type', 'text')
        if tp == 'title':        score += 25

        # S7: 页位
        if it['y0'] < 60:        score += 15
        elif it['y0'] < 120:     score += 8

        # S8: 上下文
        if idx + 1 < len(items):
            next_len = len(items[idx + 1]['text'])
            if text_len < 30 and next_len > text_len * 4:   score += 12
            elif text_len < 30 and next_len > text_len * 2:  score += 6

        # 前导页惩罚
        if it['page'] <= 2 and h_ratio < 1.30 and not level_override:
            score -= 20

        if score < min_score:
            continue

        # 确定层级
        if level_override:
            level = level_override
        elif score >= 90:        level = 1
        elif score >= 75:        level = 2
        elif score >= 65:        level = 3

        # 提取编号
        number = ''
        for pat, _ in NUM_PATTERNS:
            m = pat.match(text_clean)
            if m:
                number = m.group(0).rstrip('.。、 ')
                break

        headings.append({
            'heading': text_clean,
            'level': level,
            'score': score,
            'number': number,
            'pos': pos_map[idx][0] if idx < len(pos_map) else 0,
            'page': it['page'],
        })

    return headings


def _normalize(h):
    """标准化标题文本用于去重比较"""
    import re as _re2
    # 去编号、去空格、去标点
    h = _re2.sub(r'^[\d.IVXLCDM\u2160-\u217B]+\s*', '', h.strip())
    h = _re2.sub(r'\s+', '', h)
    return h[:40]  # 取前40字比较


def merge_with_md(md_sections, json_headings, md_text=''):
    """合并 MD + JSON 标题，文本语义去重。

    对于 JSON 独有的标题，在 md_text 中搜索真实位置；
    若 md_text 为空则丢弃 pos 不可靠的 JSON 标题。
    """
    # 构建 MD 标准化标题集合
    md_norm = {_normalize(s['heading']) for s in md_sections}
    merged = list(md_sections)

    for jh in json_headings:
        jn = _normalize(jh['heading'])
        if not jn or jn in md_norm:
            continue  # 与 MD 重复 → 跳过

        # JSON 独有的标题 → 在 MD 文本中找真实位置
        real_pos = -1
        if md_text:
            # 搜索标题原文 (取前30字作为搜索词)
            needle = jh['heading'][:30].strip()
            if needle:
                idx = md_text.find(needle)
                if idx >= 0:
                    real_pos = idx

        if real_pos >= 0:
            merged.append({
                'heading': jh['heading'],
                'pos': real_pos,
                'length': 0,
                'type': 'normative',
                '_source': 'json_enriched',
            })
            md_norm.add(jn)  # 避免后续 JSON 项重复添加

    merged.sort(key=lambda s: s['pos'])
    return merged


# ── CLI ──
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python kb_heading_extractor.py <json_path>')
        print('      python kb_heading_extractor.py --all')
        print('      python kb_heading_extractor.py --stats <json_path>')
        sys.exit(1)

    if sys.argv[1] == '--all':
        kb_json = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json')
        manifest = json.load(open(os.path.join(kb_json, 'manifest.json'), 'r', encoding='utf-8'))
        json_files = list(manifest.get('standards', {}).values())
        total, total_h = len(json_files), 0
        for i, jf in enumerate(json_files):
            jp = os.path.join(kb_json, jf)
            if not os.path.exists(jp):
                continue
            try:
                h = extract_high_conf_headings(jp)
                total_h += len(h)
                if (i + 1) % 20 == 0:
                    print(f'  进度: {i+1}/{total}, {total_h} 高置信度标题')
            except Exception as e:
                print(f'  [SKIP] {jf}: {e}')
        print(f'\n总计: {total} 文件, {total_h} 高置信度补充标题')

    elif sys.argv[1] == '--stats':
        json_path = sys.argv[2]
        items = load_json_items(json_path)
        h = extract_high_conf_headings(json_path)
        lvl_dist = Counter(s['level'] for s in h)
        print(f'总文本块: {len(items)}')
        print(f'高置信度标题 (score>=50): {len(h)}')
        for lvl in sorted(lvl_dist):
            count = lvl_dist[lvl]
            examples = [s for s in h if s['level'] == lvl][:5]
            print(f'\n  H{lvl}: {count}')
            for ex in examples:
                print(f'    s={ex["score"]:3d} | {ex["heading"][:60]}')
    else:
        json_path = sys.argv[1]
        h = extract_high_conf_headings(json_path)
        print(f'高置信度标题: {len(h)} 条\n')
        for s in h:
            prefix = '#' * s['level']
            print(f'  {prefix} {s["heading"][:70]}  (s={s["score"]}, p{s["page"]})')
