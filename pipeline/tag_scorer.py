"""浮动标签评分器 — 根据搜索命中频率动态调整专业分类标签
用法: python tag_scorer.py [--max-tags 5] [--min-score 3]
在 Phase C2 末尾自动调用

v6.12: YAML结构分离 — type: (固定) + categories: (浮动)
  - 读取 MD 文件的 categories: [...] 行 (仅浮动标签)
  - type: 行由入库管线维护, tag_scorer 不修改
  - 搜索日志共现 → 评分 → 写回 categories: 行
"""
import os, sys, re, json, math
from collections import Counter, defaultdict
from datetime import datetime

_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
from kb_core.kb import load_config

_cfg = load_config()
KB_DIR = os.path.expanduser(_cfg['paths']['kb_md'])  # RAG源
LOG_PATH = os.path.join(os.path.dirname(__file__), 'kb_search_log.jsonl')
SCORE_PATH = os.path.join(os.path.dirname(__file__), 'kb_tag_scores.json')


# ── 查询词→标签映射 (自训练) ──
def build_query_tag_map():
    """从已打标文件中学习: 查询命中某文件→该文件的分类标签关联到该查询"""
    qtag = defaultdict(Counter)
    file_tags = {}
    for fname in os.listdir(KB_DIR):
        if not fname.endswith('.md'): continue
        fpath = os.path.join(KB_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                head = f.read(500)
            m = re.search(r'^categories:\s*\[(.*?)\]', head, re.MULTILINE)
            if m:
                tags = set(t.strip() for t in m.group(1).split(',') if t.strip())
                code = re.search(r'(GB|JGJ|CJJ|CECS|DB|JTG|TCECS)\s*T?\s*\d+', fname.upper().replace(' ',''))
                if code:
                    file_tags[code.group(0).replace(' ','').replace('/','')] = tags
        except Exception:
            continue

    if not os.path.exists(LOG_PATH): return qtag

    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                entry = json.loads(line)
                query = entry.get('q', '')
                codes = entry.get('c', [])
                for c in codes:
                    if c in file_tags:
                        for tag in file_tags[c]:
                            qtag[query][tag] += 1
            except (json.JSONDecodeError, KeyError):
                continue
    return qtag


def score_tags(max_tags=5, min_score=3):
    """主评分函数: 返回 {file_code: [(tag, score), ...]}

    v6.15: IDF 加权归一 — 低频高区分度标签自动补偿。
      质量验收(85文件) idf≈1.0, 砌体结构(12文件) idf≈3.0。
    """
    qtag = build_query_tag_map()

    # ── IDF 加权: 高频标签降权, 低频区分性标签升权 ──
    tag_file_count = Counter()
    total_files = 0
    for fname in os.listdir(KB_DIR):
        if not fname.endswith('.md'): continue
        fpath = os.path.join(KB_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                head = f.read(500)
            m = re.search(r'^categories:\s*\[(.*?)\]', head, re.MULTILINE)
            if m:
                tags = set(t.strip() for t in m.group(1).split(',') if t.strip())
                if tags:
                    total_files += 1
                    for t in tags:
                        tag_file_count[t] += 1
        except Exception:
            continue

    idf_weight = {}
    for tag, count in tag_file_count.items():
        idf_weight[tag] = math.log((total_files + 1) / (1 + count))

    tag_hit = defaultdict(Counter)
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
        for line in lines[-500:]:
            try:
                entry = json.loads(line)
                query = entry.get('q', '')
                codes = entry.get('c', [])
                for c in codes:
                    if query in qtag:
                        for tag, _ in qtag[query].most_common(3):
                            # IDF 加权: 稀有标签每命中一次获得更高分数
                            tag_hit[c][tag] += idf_weight.get(tag, 1.0)
            except (json.JSONDecodeError, KeyError):
                continue

    scores = {}
    min_weighted = min_score * idf_weight.get(max(tag_file_count, key=tag_file_count.get), 1.0) if tag_file_count and min_score > 0 else min_score
    for code, tags in tag_hit.items():
        scored = [(tag, round(score, 1)) for tag, score in tags.most_common(max_tags * 2)]
        scored = [(t, s) for t, s in scored if s >= min_weighted * 0.5]
        scored.sort(key=lambda x: -x[1])
        if scored:
            scores[code] = scored[:max_tags]

    return scores


def apply_scores(scores, max_tags=5):
    """将浮动分类标签写入 YAML categories: 行。type: 行原样保留。"""
    updated = 0
    for fname in os.listdir(KB_DIR):
        if not fname.endswith('.md'): continue
        fpath = os.path.join(KB_DIR, fname)
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # 提取编号用于匹配
        code = re.search(r'(GB|JGJ|CJJ|CECS|DB|JTG|TCECS)\s*T?\s*\d+', fname.upper().replace(' ',''))
        if not code: continue
        code_val = code.group(0).replace(' ','').replace('/','')

        # 确定新分类标签: 有得分用得分, 无得分保留现有
        if code_val in scores:
            new_categories = [t for t, _ in scores[code_val][:max_tags]]
        else:
            # 保留现有 categories (无新的搜索数据)
            m = re.search(r'^categories:\s*\[(.*?)\]', content, re.MULTILINE)
            if m:
                new_categories = [t.strip() for t in m.group(1).split(',') if t.strip()][:max_tags]
            else:
                continue  # 没有 categories 行, 无法更新

        if not new_categories:
            continue

        cat_str = ', '.join(new_categories)
        new_line = f'categories: [{cat_str}]'

        if re.search(r'^categories:\s*\[.*?\]', content, re.MULTILINE):
            content = re.sub(r'^categories:\s*\[.*?\]', new_line, content, flags=re.MULTILINE)
        else:
            # YAML 头中没有 categories 行: 在 type: 行后插入
            content = re.sub(r'(^type:\s+.+\n)', r'\1' + new_line + '\n', content, flags=re.MULTILINE)

        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        updated += 1

    return updated


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--max-tags', type=int, default=5)
    p.add_argument('--min-score', type=int, default=3)
    args = p.parse_args()

    print(f'[TagScorer] 分析搜索日志...')
    scores = score_tags(args.max_tags, args.min_score)
    scored_count = len(scores)
    print(f'[TagScorer] {scored_count} 文件有浮动标签候选')

    updated = apply_scores(scores, args.max_tags)
    print(f'[TagScorer] 已更新 {updated} 文件')

    with open(SCORE_PATH, 'w', encoding='utf-8') as f:
        json.dump({k: [(t, s) for t, s in v] for k, v in scores.items()},
                  f, ensure_ascii=False, indent=2)
    print(f'[TagScorer] 分数快照: {SCORE_PATH}')


if __name__ == '__main__':
    main()
