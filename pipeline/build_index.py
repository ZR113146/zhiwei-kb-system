# -*- coding: utf-8 -*-
"""构建/增量更新 规范条款级JSON索引
支持 MinerU JSON 格式（优先）和旧 MD 格式（回退）
"""
import os, re, json, argparse, glob as gl, sys
from datetime import datetime

# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
from kb_core.kb import load_config
import kb_core.changelog as changelog; changelog.record(__file__, sys.argv)

cfg = load_config()
WORK_JSON_DIR = cfg['paths']['work_json']
JSON_KB_DIR = cfg['paths']['kb_json']
MD_KB_DIR = cfg['paths']['kb_md']
MANIFEST = cfg['paths']['manifest']
OUT = cfg['paths']['standards_index']


# ============================================================
#  文本提取
# ============================================================

def extract_clauses(text):
    """从文本提取条款: {条款号: 原文}。支持阿拉伯数字、中文数字编号"""
    clauses = {}
    patterns = [
        (r'§\s*(\d+(?:\.\d+)+)', '§'),
        (r'第\s*(\d+(?:\.\d+)+)\s*条', '条'),
        (r'(?:^|\n)\s*(\d+(?:\.\d+)+)\s+', 'num'),
        (r'(?:^|\n)\s*([IVXLCDM\u2160-\u217B]+(?:\.\d+)*)\s+', 'roman'),
        (r'(?:^|\n)\s*([一二三四五六七八九十百千]+)\s*[、．.]', 'cn'),
    ]
    paras = text.split('\n\n')
    for p in paras:
        p = p.strip()
        if not p or len(p) < 20:
            continue
        for pat, prefix in patterns:
            m = re.search(pat, p)
            if m:
                clause = f'§{m.group(1)}'
                seg = p[:2000]
                if clause in clauses:
                    # 同号段落(如正文 vs 条文说明)不覆盖,追加保留
                    if seg not in clauses[clause]:
                        clauses[clause] = (clauses[clause] + '\n\n' + seg)[:4000]
                else:
                    clauses[clause] = seg
                break
    return clauses


# ============================================================
#  JSON 读取 & 分段合并
# ============================================================

def read_json_standard(filepath):
    """从 MinerU JSON 文件读取规范，返回 (标准名, 全文)。标准名自动前置文件名中的规范编号"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        return None, None

    # 尝试从文件名中提取规范编号
    fname = os.path.basename(filepath)
    code_m = re.search(r'((?:GB\s*/?\s*T?|JGJ|CJJ|CECS|CJ\s*/?\s*T?|DB)\s*\d+[\.-]\d+(?:-\d+)?)', fname)
    std_code = code_m.group(0).replace(' ', '') if code_m else None

    # 提取标准名：取第一页 text_level=1 的文本
    name = None
    for item in data:
        if item.get('text_level') == 1 and item.get('type') == 'text':
            name = item['text'].strip()
            break
    if not name:
        name = os.path.splitext(os.path.basename(filepath))[0]

    # 按 page_idx 排序后拼接全文（段落间保留空行以匹配 extract_clauses 分段逻辑）
    sorted_items = sorted(data, key=lambda x: (x.get('page_idx', 0), data.index(x)))
    lines = []
    prev_page = -1
    prev_level = -1

    for item in sorted_items:
        text = item.get('text', '')
        if not text:
            continue
        page = item.get('page_idx', 0)
        level = item.get('text_level', 0)
        itype = item.get('type', '')

        if page != prev_page and lines:
            lines.append('')
        elif level == 1 and prev_level != 1 and lines:
            lines.append('')

        if itype == 'list' and 'list_items' in item:
            for li in item['list_items']:
                lines.append(li)
        else:
            lines.append(text)

        prev_page = page
        prev_level = level

    full_text = '\n'.join(lines)
    # 前置规范编号到标准名（如 "GB/T10801.1-2025 绝热用模塑..."）
    if std_code and std_code not in name:
        name = f'{std_code} {name}'
    return name, full_text


def merge_and_cleanup_segments():
    """检测并合并 _segN_ 前缀的分段 JSON

    扫描 WORK_JSON_DIR 中 _seg*_<prefix>.json 模式的文件，
    按分段号排序后合并为一个完整 JSON（修正 page_idx 偏移），
    删除分段文件，合并结果写入 JSON_KB_DIR，返回合并后的文件名列表。
    """
    seg_files = {}
    for fname in os.listdir(WORK_JSON_DIR):
        m = re.match(r'_seg(\d+)_(.+)\.json$', fname)
        if m:
            seg_num = int(m.group(1))
            prefix = m.group(2)
            # 去掉页号后缀 _pXXXX-XXXX，使同源的段合并到一组
            prefix = re.sub(r'_p\d{4}-\d{4}$', '', prefix)
            seg_files.setdefault(prefix, []).append((seg_num, fname))

    if not seg_files:
        return []

    print(f'检测到 {len(seg_files)} 组待合并分段')
    merged_names = []

    for prefix, segments in seg_files.items():
        segments.sort(key=lambda x: x[0])
        output_name = f'{prefix}.json'

        merged = []
        offset = 0
        print(f'  合并: {prefix} ({len(segments)} 段)')

        for seg_num, fname in segments:
            fpath = os.path.join(WORK_JSON_DIR, fname)
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 计算本段原始页数
            orig_pages = sorted(set(item.get('page_idx', 0) for item in data))
            max_orig = orig_pages[-1] if orig_pages else 0
            min_orig = orig_pages[0] if orig_pages else 0

            # 应用偏移
            for item in data:
                if 'page_idx' in item:
                    item['page_idx'] += offset

            merged.extend(data)

            # 删除分段文件
            os.remove(fpath)

            offset += (max_orig - min_orig + 1)

        # 保存合并结果
        output_path = os.path.join(JSON_KB_DIR, output_name)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(merged, f, ensure_ascii=False)

        merged_names.append(output_name)
        print(f'    → {output_name} ({len(merged)} 条, {offset} 页)')

    print(f'合并完成: {len(merged_names)} 个文件')
    return merged_names


# ============================================================
#  索引构建
# ============================================================

def build_from_json():
    """从 JSON 知识库全量构建索引"""
    db = {"_meta": {
        "built": datetime.now().isoformat(),
        "source": JSON_KB_DIR,
        "mode": "full-json"
    }}
    count = 0
    found = 0

    if not os.path.exists(JSON_KB_DIR):
        print(f'[WARN] JSON目录不存在: {JSON_KB_DIR}')
        return db, 0, 0

    for fname in os.listdir(JSON_KB_DIR):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(JSON_KB_DIR, fname)
        try:
            name, text = read_json_standard(fpath)
        except Exception as e:
            print(f'  [SKIP] {fname}: JSON解析失败 ({e})')
            continue

        if not name or not text:
            print(f'  [SKIP] {fname}: 无有效内容')
            continue

        clauses = extract_clauses(text)
        if clauses:
            db[name] = clauses
            count += len(clauses)
            found += 1
            print(f'  {name}: {len(clauses)} clauses')
        else:
            print(f'  [WARN] {name}: 未提取到条款')

    return db, found, count


def build_from_md():
    """从旧 MD 知识库全量构建索引（回退方案）"""
    db = {"_meta": {
        "built": datetime.now().isoformat(),
        "source": MD_KB_DIR,
        "mode": "full-md"
    }}
    count = 0
    found = 0

    if not os.path.exists(MD_KB_DIR):
        print(f'[WARN] MD目录不存在: {MD_KB_DIR}')
        return db, 0, 0

    for fname in os.listdir(MD_KB_DIR):
        if not fname.endswith('.md'):
            continue
        name = fname.replace('.md', '').strip()
        fpath = os.path.join(MD_KB_DIR, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            text = f.read()
        clauses = extract_clauses(text)
        if clauses:
            db[name] = clauses
            count += len(clauses)
            found += 1
            print(f'  {name}: {len(clauses)} clauses')

    return db, found, count


def build_full():
    """全量构建：优先JSON，MD补充"""
    print('=== 从 JSON 知识库读取 ===')
    db, json_count, json_clauses = build_from_json()

    # 用MD补充JSON中没有的规范
    json_names = set(k for k in db if not k.startswith('_'))
    md_db, md_count, md_clauses = build_from_md()

    added = 0
    for name, clauses in md_db.items():
        if name.startswith('_'):
            continue
        if name not in json_names:
            db[name] = clauses
            added += 1
            json_clauses += len(clauses)

    total = json_count + added
    if added > 0:
        print(f'\n=== MD补充: {added} 部规范 ===')

    json.dump(db, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'\n索引完成: {total} 部规范, {json_clauses} 条条款')
    print(f'  JSON源: {json_count} 部')
    print(f'  MD补充: {added} 部')
    print(f'保存: {OUT} ({os.path.getsize(OUT)//1024}KB)')


def build_incremental():
    """增量更新：先合并分段，再处理 manifest 中未记录的新 JSON"""
    # ---- 1. 检测并合并分段 ----
    merged = merge_and_cleanup_segments()

    # ---- 2. 加载 manifest ----
    manifest = {"_meta": {}, "standards": {}}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, 'r', encoding='utf-8-sig') as f:
            manifest = json.load(f)

    known_files = set(manifest.get('standards', {}).values())

    # ---- 3. 加载现有索引 ----
    index = {"_meta": {"built": "", "source": JSON_KB_DIR, "mode": "incremental"}}
    if os.path.exists(OUT):
        with open(OUT, 'r', encoding='utf-8') as f:
            index = json.load(f)

    # ---- 4. 扫描新 JSON 文件 ----
    if not os.path.exists(JSON_KB_DIR):
        print('[WARN] JSON目录不存在')
        return

    new_files = []
    for fname in os.listdir(JSON_KB_DIR):
        if not fname.endswith('.json'):
            continue
        if fname in known_files:
            continue
        new_files.append(fname)

    if not new_files:
        if not merged:
            print('无新增文件，跳过')
        return

    print(f'\n发现 {len(new_files)} 个新文件')

    added_count = 0
    added_clauses = 0

    for fname in new_files:
        fpath = os.path.join(JSON_KB_DIR, fname)
        try:
            name, text = read_json_standard(fpath)
        except Exception as e:
            print(f'  [SKIP] {fname}: 解析失败 ({e})')
            continue

        if not name or not text:
            print(f'  [SKIP] {fname}: 无有效内容')
            continue

        # 避免重名覆盖：同名时从文件名提取分册/卷号做区分
        if name in index and not name.startswith('_'):
            vol = re.search(r'第(\S+册)', fname)
            if vol:
                name = f'{name}·{vol.group(1)}'
                print(f'  [DEDUP] 重名，区分为: {name}')
            else:
                name = os.path.splitext(fname)[0][:80]
                print(f'  [DEDUP] 重名，改用文件名: {name}')

        clauses = extract_clauses(text)
        if clauses:
            index[name] = clauses
            manifest['standards'][name] = fname
            added_count += 1
            added_clauses += len(clauses)
            print(f'  + {name}: {len(clauses)} 条款')
        else:
            print(f'  [WARN] {name}: 未提取到条款')

    if added_count == 0:
        if not merged:
            print('无有效新增')
        return

    # ---- 5. 保存 ----
    index['_meta']['built'] = datetime.now().isoformat()
    index['_meta']['mode'] = 'incremental'
    manifest['_meta']['updated'] = datetime.now().isoformat()

    json.dump(index, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump(manifest, open(MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    total = len([k for k in index if not k.startswith('_')])
    total_clauses = sum(len(v) for k, v in index.items() if not k.startswith('_'))
    print(f'\n增量完成: +{added_count} 部, 合计 {total} 部规范 / {total_clauses} 条款')
    print(f'manifest 已更新: {os.path.getsize(MANIFEST)}B')


# ============================================================
#  入口
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', action='store_true', help='全量重建索引')
    parser.add_argument('--json-only', action='store_true', help='仅从JSON源构建')
    parser.add_argument('--md-only', action='store_true', help='仅从MD源构建')
    parser.add_argument('--incremental', action='store_true', help='增量更新（含分段自动合并）')
    args = parser.parse_args()

    if args.incremental:
        build_incremental()
        return

    if args.json_only:
        db, found, count = build_from_json()
        json.dump(db, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'\nJSON索引: {found} 部规范, {count} 条条款')
        return

    if args.md_only:
        db, found, count = build_from_md()
        json.dump(db, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'\nMD索引: {found} 部规范, {count} 条条款')
        return

    # 默认：全量构建
    build_full()


if __name__ == '__main__':
    main()
