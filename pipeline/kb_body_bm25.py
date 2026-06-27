"""Build paragraph-level BM25 index from data/index/*.md body text (v6.18).

Each ## section's body text is tokenized with jieba (custom dict from term lists),
producing a BM25 index that enables full-text search of standard body content.

The BM25 index runs as a PARALLEL entry to L1 heading search — it adds candidates
that heading search misses, without modifying existing weights or post-processing.

Output: data/kb_json/kb_body_bm25.json (~20-30MB)
"""
import os, re, json, sys, math
from collections import defaultdict

KNOWLEDGE = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
SEARCH_INDEX = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_search_index.json')
TERM_MAP = os.path.join(os.path.dirname(__file__), 'kb_term_map.json')
TERM_INDEX = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_term_index.json')
OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_body_bm25.json')

# BM25 parameters (standard defaults, proven across decades of IR research)
K1 = 1.5   # term frequency saturation
B = 0.75   # length normalization


def load_term_dict():
    """Build jieba user dictionary from term map + term index."""
    terms = set()
    # From term map (202 groups of synonyms)
    if os.path.exists(TERM_MAP):
        with open(TERM_MAP, 'r', encoding='utf-8') as f:
            tm = json.load(f)
        for group in tm.values() if isinstance(tm, dict) else tm:
            if isinstance(group, list):
                terms.update(t.lower() for t in group)
    # From term index (877 indexed terms)
    if os.path.exists(TERM_INDEX):
        with open(TERM_INDEX, 'r', encoding='utf-8') as f:
            ti = json.load(f)
        idx = ti.get('index', {})
        terms.update(k.lower() for k in idx.keys())
    return terms


def tokenize(text, term_set):
    """Tokenize text using jieba with term list as custom dict, filtering stop words."""
    import jieba
    # Add term set as custom dictionary
    for t in term_set:
        if len(t) >= 2:
            jieba.add_word(t)

    tokens = jieba.lcut(text.lower())

    # Filter: keep Chinese chars (>=2), alphanumeric terms, numbers
    result = []
    for t in tokens:
        t = t.strip()
        if len(t) < 2:
            continue
        if re.match(r'^[\u4e00-\u9fff]{2,}$', t):  # Chinese word >= 2 chars
            result.append(t)
        elif re.match(r'^[a-z0-9]{2,}$', t):  # English/number code
            result.append(t)
        elif t in term_set:  # Single-char but in term set
            result.append(t)
    return result


def build():
    import jieba

    # Load section positions from search index
    with open(SEARCH_INDEX, 'r', encoding='utf-8') as f:
        si = json.load(f)
    headings_index = si.get('index', {})

    # Load term dictionary
    term_set = load_term_dict()
    print(f'Term dict: {len(term_set)} unique terms')

    # Register with jieba
    for t in term_set:
        if len(t) >= 2:
            jieba.add_word(t)

    # Build BM25 index per file/section
    files_list = []          # file_id → filename
    sections_dict = {}       # "fid:sid" → heading text
    doc_lengths = {}         # "fid:sid" → token count
    inverted = defaultdict(list)  # term → [(fid, sid, tf), ...]

    total_tokens = 0
    total_docs = 0
    skipped = 0

    md_files = sorted(f for f in os.listdir(KNOWLEDGE) if f.endswith('.md'))

    for fid, fname in enumerate(md_files):
        fpath = os.path.join(KNOWLEDGE, fname)
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

        sections = headings_index.get(fname, [])
        if not sections:
            continue

        files_list.append(fname)

        for sid, sec in enumerate(sections):
            heading = sec.get('heading', '')
            start_pos = sec.get('pos', 0)

            # Find next section start (or end of file for last section)
            if sid + 1 < len(sections):
                end_pos = sections[sid + 1].get('pos', len(text))
            else:
                end_pos = len(text)

            body = text[start_pos:end_pos]
            tokens = tokenize(body, term_set)

            if len(tokens) < 5:  # Skip very short sections
                skipped += 1
                continue

            doc_id = f'{fid}:{sid}'
            sections_dict[doc_id] = heading
            doc_lengths[doc_id] = len(tokens)
            total_tokens += len(tokens)
            total_docs += 1

            # Count term frequencies in this section
            tf_map = defaultdict(int)
            for t in tokens:
                tf_map[t] += 1

            for term, tf in tf_map.items():
                inverted[term].append([fid, sid, tf])

    avg_len = total_tokens / max(total_docs, 1)

    # Write index
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump({
            '_files': files_list,
            '_sections': sections_dict,
            '_doc_count': total_docs,
            '_avg_len': round(avg_len, 1),
            '_doc_lengths': doc_lengths,
            '_k1': K1,
            '_b': B,
            'index': {k: v for k, v in inverted.items()}
        }, f, ensure_ascii=False)

    size_mb = os.path.getsize(OUTPUT) / 1024 / 1024
    print(f'BM25 index: {total_docs} sections from {len(files_list)} files ({skipped} skipped)')
    print(f'Terms: {len(inverted)} unique, avg doc length: {avg_len:.1f} tokens')
    print(f'Output: {OUTPUT} ({size_mb:.1f}MB)')


if __name__ == '__main__':
    build()
