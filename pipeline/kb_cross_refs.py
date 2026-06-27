"""跨标准引用提取 — 扫描 MD 文件提取 "应符合 GBxxx" 类引用
输出: data/kb_json/kb_cross_refs.json
用法: python kb_cross_refs.py
"""
import json, os, re

KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_cross_refs.json')

# Reference patterns
REF_PATTERNS = [
    # "应符合 GB 50204" / "应符合现行 GB50204"
    re.compile(r'(?:应符合|尚应符合|应符合现行|除应符合|尚应符合现行)\s*.{0,30}?(GB|JGJ|CJJ|CECS|TCECS|JC|DB|JTG|RISN)[\sT/_]?\s*(\d+(?:\.\d+)?)', re.IGNORECASE),
    # "执行 GB 50010" / "参照 GB 50300"
    re.compile(r'(?:执行|参见|参照|见|按)\s*.{0,20}?(GB|JGJ|CJJ|CECS|TCECS|JC|DB|JTG|RISN)[\sT/_]?\s*(\d+(?:\.\d+)?)', re.IGNORECASE),
    # "GB 50010 的有关规定"
    re.compile(r'(?:现行|现行国家标准|国家标准|行业标准)\s*.{0,10}?(GB|JGJ|CJJ|CECS|TCECS|JC|DB|JTG|RISN)[\sT/_]?\s*(\d+(?:\.\d+)?)', re.IGNORECASE),
]

def extract():
    md_files = sorted([f for f in os.listdir(KB_DIR) if f.endswith('.md')])

    refs = []  # [{source_file, source_code, target_code, context}]
    target_to_source = {}  # target_code → set of source_codes (inverted for PPR edges)

    for fn in md_files:
        fp = os.path.join(KB_DIR, fn)
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            continue

        # Extract source standard code
        src_m = re.search(r'(GB|JGJ|CJJ|CECS|TCECS|JC|DB|JTG|RISN)[\sT/_]?\s*(\d+(?:\.\d+)?)', fn)
        src_code = (src_m.group(1) + src_m.group(2)).replace(' ', '').replace('_', '/') if src_m else fn[:30]

        seen_targets = set()
        for pat in REF_PATTERNS:
            for m in pat.finditer(content):
                prefix = m.group(1).upper()
                number = m.group(2)
                target = (prefix + number).replace(' ', '')

                if target == src_code:
                    continue  # Self-reference
                if target in seen_targets:
                    continue
                seen_targets.add(target)

                ctx_start = max(0, m.start() - 20)
                ctx_end = min(len(content), m.end() + 30)
                context = content[ctx_start:ctx_end].replace('\n', ' ').strip()

                refs.append({
                    'source_file': fn,
                    'source_code': src_code,
                    'target_code': target,
                    'context': context[:100]
                })

                if target not in target_to_source:
                    target_to_source[target] = set()
                target_to_source[target].add(src_code)

    output = {
        '_meta': {
            'total_refs': len(refs),
            'unique_targets': len(target_to_source),
            'files_scanned': len(md_files)
        },
        'refs': refs,
        'target_to_source': {k: list(v) for k, v in target_to_source.items()}
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    print('Cross-refs: %d references, %d unique targets, %.1fKB' % (
        len(refs), len(target_to_source), os.path.getsize(OUTPUT)/1024))

    # Show top referenced standards
    print()
    print('=== Most referenced standards ===')
    top = sorted(target_to_source.items(), key=lambda x: -len(x[1]))[:10]
    for target, sources in top:
        print('  %s: referenced by %d files (%s...)' % (target, len(sources), ', '.join(list(sources)[:3])))

if __name__ == '__main__':
    extract()
