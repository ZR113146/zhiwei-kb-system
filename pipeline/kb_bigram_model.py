"""Bigram语言模型 — 条件熵+异常占比检测
用法: python kb_bigram_model.py --build       # 从KB训练模型
      python kb_bigram_model.py --check MD文件  # 检验单个文件
从 kb_import.py 调用: check_content_quality(content) → (passed, reason)
"""
import os, sys, json, math
from collections import Counter, defaultdict

# 配置文件路径
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
from kb_core.kb import load_config
_cfg = load_config()
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'kb_bigram.json')
KB_MD_DIR = _cfg['paths'].get('kb_md_lib', os.path.join(os.path.dirname(__file__), '..', 'data', 'md_lib_v2'))

# ── 模型训练 ──
def build_model():
    """从kb_md全量训练bigram模型 + Good-Turing平滑"""
    print(f'训练: {KB_MD_DIR}')
    bigram_counts = defaultdict(Counter)

    files = [f for f in os.listdir(KB_MD_DIR) if f.endswith('.md')]
    for fname in files:
        fpath = os.path.join(KB_MD_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        for i in range(len(text) - 1):
            bigram_counts[text[i]][text[i+1]] += 1

    # Good-Turing: 统计出现频次分布
    freq_of_freq = Counter()
    for next_chars in bigram_counts.values():
        for count in next_chars.values():
            freq_of_freq[count] += 1

    N1 = freq_of_freq.get(1, 0)   # 仅出现1次的bigram数
    N_total = sum(c * n for c, n in freq_of_freq.items())  # 总bigram数
    V = len(bigram_counts)  # 词汇表大小

    # Good-Turing: P(unseen_mass) = N1/N, 分配给 V² 个可能组合
    # 每个未见bigram: P = N1 / (N * (V * alpha)), alpha经验值
    if N1 > 0 and N_total > 0:
        p_min = N1 / (N_total * V * 10)  # 单个未见转移的估计概率
    else:
        p_min = 1.0 / (N_total + 1) if N_total > 0 else 1e-10

    # 转为概率表 (仅存P>0的，节省空间)
    prob_table = {}
    for c1, next_chars in bigram_counts.items():
        total = sum(next_chars.values())
        prob_table[c1] = {c2: count / total for c2, count in next_chars.items()}

    model = {
        'probs': prob_table,
        'p_min': p_min,
        'N_total': N_total,
        'V': V,
        'N1': N1,
        '_file_count': len(files)
    }

    with open(MODEL_PATH, 'w', encoding='utf-8') as f:
        json.dump(model, f, ensure_ascii=False)

    print(f'  总bigram: {N_total}  词汇表: {V}  N1: {N1}')
    print(f'  P_unseen: {p_min:.2e}')
    print(f'  已保存: {MODEL_PATH} ({os.path.getsize(MODEL_PATH)/1024/1024:.1f}MB)')
    return model


# ── 模型加载 ──
_model_cache = None

# ── 基线漂移检测 ──
RECALIBRATE_DELTA = 10  # KB文件数变化超过此值时建议重建模型

def load_model():
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    if os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, 'r', encoding='utf-8') as f:
            _model_cache = json.load(f)
        # 检测 KB 文件数变化
        current_count = len([f for f in os.listdir(KB_MD_DIR) if f.endswith('.md')])
        trained_count = _model_cache.get('_file_count', 0)
        if abs(current_count - trained_count) >= RECALIBRATE_DELTA:
            print(f'  [WARN] Bigram模型基线可能过时 (训练={trained_count}, 当前={current_count})')
            print(f'  [WARN] 建议执行: python kb_bigram_model.py --build')
        return _model_cache
    return None


# ── 质量检验 ──
ANOMALY_THRESHOLD = 0.01  # 异常占比>1% → 拦截

def check_content_quality(content, fname=''):
    """P_min天花板计数: 只看最异常的5%转移中, 有多少触到了Good-Turing天花板。
    原理: 正常文档天花板恒为0(241/241), 半页扫描的乱码转移天然触发P_min。
          只看top5%避免正常转移稀释信号。
    阈值: top5%中P_min占比>2% → 拦截 (放过JPEG渲染≤1%, 拦截截断≥3.5%)
    """
    model = load_model()
    if model is None:
        return True, 'no_model'

    prob_table = model['probs']
    p_min = model['p_min']

    if len(content) < 2:
        return True, 'too_short'

    # 计算全文字符转移的 -log2P
    import math
    lps = []
    for i in range(len(content) - 1):
        c1, c2 = content[i], content[i+1]
        prob = prob_table.get(c1, {}).get(c2, p_min)
        lps.append(-math.log2(max(prob, 1e-15)))

    # 取顶部5%, 统计P_min(22.6)的比例
    lps.sort(reverse=True)
    top_5pct = lps[:max(1, int(len(lps) * 0.05))]
    p_min_count = sum(1 for x in top_5pct if x > 22)
    p_min_ratio = p_min_count / len(top_5pct)

    P_MIN_THRESHOLD = 0.03  # v6.20: 全库扫描P99=2.1%, 3%覆盖100%已有文件
    if p_min_ratio > P_MIN_THRESHOLD:
        return False, f'内容质量异常: P_min占比{p_min_ratio:.1%} (阈值{P_MIN_THRESHOLD:.0%})'
    return True, ''


# ── CLI ──
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python kb_bigram_model.py --build | --check <md文件>")
        sys.exit(1)

    if sys.argv[1] == '--build':
        build_model()
    elif sys.argv[1] == '--check':
        if len(sys.argv) < 3:
            print("请指定MD文件路径")
            sys.exit(1)
        model = load_model()
        if model is None:
            print("模型不存在，请先 --build")
            sys.exit(1)
        with open(sys.argv[2], 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        passed, reason = check_content_quality(content, sys.argv[2])
        print(f"{'PASS' if passed else 'REJECT'}: {reason}")
