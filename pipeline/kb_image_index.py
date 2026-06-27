"""Build image metadata index from data/index/*.md files.

Captures for each image: code (规范号), section (章节标题), context_before/after
(图片前后200字上下文), offset in file. Zero new dependencies, zero file changes.

Output: data/kb_json/kb_image_index.json (~3-5MB for 26,075 images)
"""
import os, re, json, sys

KNOWLEDGE = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
IMAGE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'images')
OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_image_index.json')

RE_IMAGE = re.compile(r'!\[\]\(images/([^)]+)\)')
RE_HEADING = re.compile(r'^#{1,3}\s+(.+)$', re.MULTILINE)
RE_CODE = re.compile(r'((?:GB|JGJ|CJJ|CECS|CJ|DB|JTG|TCECS)[\s/]*T?\s*\d+(?:\.\d+)?(?:-\d+)?)')


def extract_code_from_filename(fname):
    m = RE_CODE.search(fname)
    return m.group(1).replace(' ', '') if m else None


def extract_sections(text):
    """Return list of (heading_text, start_offset)."""
    sections = []
    for m in RE_HEADING.finditer(text):
        sections.append((m.group(1).strip(), m.start()))
    return sections


def find_section_for_offset(sections, offset):
    """Find the closest preceding heading for a given byte offset."""
    current = None
    for heading, pos in sections:
        if pos <= offset:
            current = heading
        else:
            break
    return current


def build():
    md_files = sorted(f for f in os.listdir(KNOWLEDGE) if f.endswith('.md'))
    entries = []
    total_images = 0

    for fname in md_files:
        fpath = os.path.join(KNOWLEDGE, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            text = f.read()

        code = extract_code_from_filename(fname)
        sections = extract_sections(text)
        images = list(RE_IMAGE.finditer(text))

        for img_match in images:
            img_name = img_match.group(1)
            img_path = f'images/{img_name}'
            offset = img_match.start()

            # Verify image file exists
            if not os.path.exists(os.path.join(IMAGE_DIR, img_name)):
                continue

            section = find_section_for_offset(sections, offset)

            # Extract context: up to 200 chars before/after, excluding the image tag itself
            ctx_start = max(0, offset - 200)
            ctx_end = min(len(text), offset + len(img_match.group(0)) + 200)
            context_before = text[ctx_start:offset].strip()[-200:]
            context_after = text[offset + len(img_match.group(0)):ctx_end].strip()[:200]

            entries.append({
                'image': img_path,
                'image_name': img_name,
                'code': code,
                'section': section,
                'context_before': context_before,
                'context_after': context_after,
                'file': fname,
                'offset': offset
            })
            total_images += 1

    # v6.18: 章节锚点补全 — 已索引 2,039 张, 补充未索引图片的章节标题上下文
    indexed = set(e['image_name'] for e in entries)
    anchor_added = 0
    for fname in md_files:
        fpath = os.path.join(KNOWLEDGE, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            text = f.read()
        code = extract_code_from_filename(fname)
        sections = extract_sections(text)
        # Find all image references (including <img src="..."> without ![] wrapper)
        all_imgs = set()
        for m in re.finditer(r'(?:src="images/|!\[\]\(images/)([^")]+)', text):
            all_imgs.add(m.group(1))
        for img_name in all_imgs:
            if img_name in indexed:
                continue
            if not os.path.exists(os.path.join(IMAGE_DIR, img_name)):
                continue
            # Find nearest section
            img_match = re.search(re.escape(f'images/{img_name}'), text)
            offset = img_match.start() if img_match else 0
            section = find_section_for_offset(sections, offset)
            entries.append({
                'image': f'images/{img_name}',
                'image_name': img_name,
                'code': code,
                'section': section,
                'context_before': f'[章节锚点: {section or "未知"}]',
                'context_after': '',
                'file': fname,
                'offset': offset,
                'source': 'section_anchor',
            })
            anchor_added += 1
            indexed.add(img_name)

    total_images = len(entries)
    # Write index
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump({
            'total': total_images,
            'entries': entries,
            'built': f'{len(md_files)} md files scanned, {anchor_added} section anchors added'
        }, f, ensure_ascii=False, indent=2)

    print(f'Image index: {total_images} images ({anchor_added} section anchors) from {len(md_files)} MD files')
    print(f'Output: {OUTPUT} ({os.path.getsize(OUTPUT)/1024/1024:.1f}MB)')


if __name__ == '__main__':
    build()
