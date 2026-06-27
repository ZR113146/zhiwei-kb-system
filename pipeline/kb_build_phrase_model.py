"""短语模型构建 (v6.23 — 含 term_map 白名单强制注入)
替代内联脚本，确保关键术语不被词频阈值过滤
用法: python kb_build_phrase_model.py
输出: data/kb_json/kb_phrase_model.json
"""
import json, os, re
from collections import Counter
import jieba

KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
TERM_MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kb_term_map.json')
OUTPUT = os.path.join(KB_DIR, 'kb_phrase_model.json')

def build():
    # 1. Tokenize all MD files
    md_files = [f for f in os.listdir(KB_DIR) if f.endswith('.md')]
    word_freq = Counter()
    bigram_freq = Counter()

    for fn in md_files:
        fp = os.path.join(KB_DIR, fn)
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            if content.startswith('---'):
                idx = content.find('---', 3)
                if idx > 0: content = content[idx+3:]
            tokens = [t.strip() for t in jieba.lcut(content) if len(t.strip()) >= 2]
            for t in tokens:
                word_freq[t] += 1
            for i in range(len(tokens)-1):
                bigram_freq[(tokens[i], tokens[i+1])] += 1
        except Exception as e:
            print('  Skip %s: %s' % (fn[:50], e))

    # 2. Build vocabulary with term_map whitelist
    words_set = set(w for w, c in word_freq.items() if c >= 2)

    # v6.23: 强制注入 term_map 白名单 — 即使词频<2也保留
    whitelist_added = 0
    if os.path.exists(TERM_MAP_PATH):
        with open(TERM_MAP_PATH, 'r', encoding='utf-8') as f:
            term_map = json.load(f)
        for vs in term_map.values():
            for v in vs:
                if len(v) >= 2 and v not in words_set:
                    words_set.add(v)
                    whitelist_added += 1
    print('Whitelist injected: %d terms from term_map' % whitelist_added)

    words = sorted(words_set)
    w2id = {w: i for i, w in enumerate(words)}

    # 3. Build bigram list using word IDs
    bg = []
    for (w1, w2), freq in bigram_freq.items():
        i1 = w2id.get(w1, -1)
        i2 = w2id.get(w2, -1)
        if i1 >= 0 and i2 >= 0:
            bg.append([i1, i2, freq])

    # 4. Save
    output = {'words': words, 'bg': bg}
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    size_mb = os.path.getsize(OUTPUT) / 1024 / 1024
    print('Phrase model: %d words, %d bigrams, %.1fMB' % (len(words), len(bg), size_mb))
    print('Saved: %s' % OUTPUT)

if __name__ == '__main__':
    build()
