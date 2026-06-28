#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""句子文本提取 — 从 MD 文件中精确提取 20,081 条句子的文本

输入:
  data/kb_json/kb_sentence_meta.json  — 句子元数据 (file, heading, fid, sid, type)
  data/kb_json/kb_search_index.json   — 章节定位 (pos, length)
  data/index/*.md                   — 241 个 MD 文件

输出:
  data/kb_json/kb_sentence_text.json  — [{sid, text, heading, file, fid}]
"""
import json, os, sys, re, time
from collections import defaultdict

KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
META_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_sentence_meta.json')
INDEX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_search_index.json')
OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_sentence_text.json')

def main():
    # 1. Load data
    print("Loading metadata...")
    with open(META_PATH, 'r', encoding='utf-8') as f:
        sent_meta = json.load(f)
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        si = json.load(f)
    print(f"  {len(sent_meta)} sentences, {len(si['index'])} files in search index")

    # 2. Group sentences by (file_name, heading)
    #    Each heading may have multiple sentences (sid 0, 1, 2, ...)
    sent_by_file_heading = defaultdict(list)
    for sid_global, meta in enumerate(sent_meta):
        key = (meta['file'], meta.get('heading', ''))
        sent_by_file_heading[key].append((sid_global, meta.get('sid', 0), meta.get('type', 'normative')))
    print(f"  Grouped into {len(sent_by_file_heading)} (file, heading) pairs")

    # 3. Build search index lookup: file_name → sorted sections
    si_by_file = {}
    for fname, sections in si['index'].items():
        si_by_file[fname] = sorted(sections, key=lambda s: s['pos'])

    # 4. Extract sentence texts
    print("Extracting sentence texts...")
    t0 = time.time()
    output = []  # [{sid, text, heading, file, fid}]
    matched = 0
    unmatched = 0

    for (fname, heading), sents in sent_by_file_heading.items():
        # Find matching section in search index
        sections = si_by_file.get(fname, [])
        section_text = None

        for sec in sections:
            if sec.get('heading', '') == heading:
                # Found matching section — extract text from MD
                md_path = os.path.join(KB_DIR, fname)
                if not os.path.exists(md_path):
                    break
                try:
                    with open(md_path, 'r', encoding='utf-8', errors='replace') as f:
                        md_text = f.read()
                except:
                    break

                pos = sec['pos']
                length = sec.get('length', 2000)
                chunk = md_text[pos:pos + length]

                # Split into sentences
                # Strategy: split by Chinese/English sentence-ending punctuation
                # and by Markdown heading boundaries
                raw_sentences = re.split(r'([。！？；\n](?=[^\n]))', chunk)

                # Merge back with delimiters
                merged = []
                buf = ""
                for part in raw_sentences:
                    buf += part
                    if re.search(r'[。！？\n]$', buf) and len(buf.strip()) > 5:
                        clean = buf.strip()
                        if clean and not clean.startswith('#') and len(clean) >= 3:
                            merged.append(clean)
                        buf = ""
                if buf.strip() and len(buf.strip()) >= 3:
                    merged.append(buf.strip())

                # Assign sentences to sentence_meta entries in order
                sents_sorted = sorted(sents, key=lambda x: x[1])  # sort by sid
                for idx, (sid_global, sid_local, stype) in enumerate(sents_sorted):
                    if idx < len(merged):
                        text = merged[idx][:2000]  # Cap length
                    else:
                        text = merged[-1][:2000] if merged else chunk[:500]
                    output.append({
                        'sid': sid_global,
                        'text': text,
                        'heading': heading,
                        'file': fname,
                        'fid': sent_meta[sid_global].get('fid', -1),
                        'type': stype,
                    })
                    matched += 1
                break  # Found and processed this heading
        else:
            # No matching section — use heading as text fallback
            for sid_global, sid_local, stype in sents:
                output.append({
                    'sid': sid_global,
                    'text': heading,
                    'heading': heading,
                    'file': fname,
                    'fid': sent_meta[sid_global].get('fid', -1),
                    'type': stype,
                })
                unmatched += 1

    # 5. Sort by sid and save
    output.sort(key=lambda x: x['sid'])

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    elapsed = time.time() - t0
    size_mb = os.path.getsize(OUT_PATH) / 1024 / 1024
    print(f"  Matched: {matched}, Unmatched (fallback): {unmatched}")
    print(f"  Total output: {len(output)} sentences")
    print(f"  Time: {elapsed:.0f}s, Size: {size_mb:.1f} MB")
    print(f"Saved: {OUT_PATH}")

    # 6. Quick quality check
    print("\nQuality samples:")
    for entry in output[:3]:
        print(f"  [{entry['sid']}] {entry['heading'][:40]}: {entry['text'][:80]}...")

if __name__ == '__main__':
    main()
