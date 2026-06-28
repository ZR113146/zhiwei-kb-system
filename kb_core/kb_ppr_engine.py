# -*- coding: utf-8 -*-
"""KB PPR 主发现引擎 — v7.0 搜索框架 Stage 1

格PPR 动态分词 → 多信号种子融合 → 图PPR传播 → 交替强化 → 文件候选集

架构:
  PPRDiscoveryEngine.discover(query, ...)
    ├── _lattice_seeds()      — 字符格PPR: 动态tokenization + bigram条件概率 + 语境桥接
    ├── _build_seed_vector()  — 多信号融合: 格PPR(75%) + 向量文件(10%) + 句子向量(15%)
    ├── _propagate()          — Scipy CSR 稀疏PPR, 5轮 alpha=0.85
    └── _reinforce()          — Top-5 文件反馈 → 种子增强 → 再传播 (max 2轮)

依赖: kb_ppr_graph.json, kb_phrase_model.json, kb_word_vectors_v2.npy (可选)
"""

import os, re, json
import numpy as np

# ── Paths ──────────────────────────────────────────────
_KB_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_KB_DIR)

def _load_paths():
    cfg_path = os.path.join(_KB_DIR, 'kb.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    paths = cfg.get('paths', {})
    resolved = {}
    for key, value in paths.items():
        if not isinstance(value, str):
            continue
        expanded = os.path.expanduser(value)
        resolved[key] = expanded if os.path.isabs(expanded) else os.path.join(_ROOT_DIR, expanded)
    return resolved

_PATHS = _load_paths()
PPR_PATH = _PATHS['kb_ppr_graph']
PM_PATH = _PATHS['kb_phrase_model']
WV_PATH = _PATHS['kb_word_vectors']
WV_VOCAB_PATH = _PATHS['kb_word_vocab']

# ── Stop words ─────────────────────────────────────────
_NL_FILLERS = {'的', '了', '是', '在', '和', '也', '就', '都', '而', '及', '与', '或', '等',
               '要', '有', '不', '会', '可以', '能', '可', '该', '其', '应', '宜', '当',
               'a', 'an', 'the', 'of', 'in', 'on', 'to', 'for', 'and', 'or', 'is', 'are',
               '怎么', '如何', '什么', '哪些', '哪种', '为何', '为什么', '怎样', '多少',
               '怎么办', '要注意', '按规定', '应符合', '的要求', '的方法', '的处理'}


class PPRDiscoveryEngine:
    """PPR 主发现引擎 — 图搜索驱动候选文件发现"""

    def __init__(self):
        self._graph = None
        self._graph_loaded = False
        self._w2id = {}
        self._ppr_matrix = None
        self._phrase_model = None
        self._bg_probs = {}
        self._bg_w2id = {}
        self._word_vecs_norm = None
        self._word_vocab = {}
        self._ctx_search_index = None
        self._ctx_term_index = None
        self._code_to_fid = {}

    # ── Lazy loading ───────────────────────────────────

    def _ensure_graph(self):
        if self._graph_loaded:
            return self._graph is not None
        self._graph_loaded = True
        if not os.path.exists(PPR_PATH):
            return False
        try:
            with open(PPR_PATH, 'r', encoding='utf-8') as f:
                self._graph = json.load(f)
            words = self._graph.get('words', [])
            self._w2id = {w: i for i, w in enumerate(words)}
            # Pre-load jieba vocabulary from graph words
            import jieba
            for w in words:
                if len(w) >= 2:
                    jieba.add_word(w)
            self._build_csr_matrix()
            self._build_code_fid_map()
            return True
        except Exception:
            self._graph = None
            return False

    def _ensure_phrase_model(self):
        if self._phrase_model is not None:
            return
        if not os.path.exists(PM_PATH):
            self._phrase_model = {}
            return
        try:
            with open(PM_PATH, 'r', encoding='utf-8') as f:
                self._phrase_model = json.load(f)
            words_pm = self._phrase_model.get('words', [])
            w2id_pm = {w: i for i, w in enumerate(words_pm)}
            total_by_src = {}
            bg_probs = {}
            for entry in self._phrase_model.get('bg', []):
                src, tgt, freq = entry[0], entry[1], entry[2]
                total_by_src[src] = total_by_src.get(src, 0) + freq
                bg_probs[(src, tgt)] = freq
            for (src, tgt), freq in bg_probs.items():
                bg_probs[(src, tgt)] = freq / max(total_by_src.get(src, 1), 1)
            self._bg_probs = bg_probs
            self._bg_w2id = {w: w2id_pm.get(w, -1) for w in self._w2id}
        except Exception:
            self._phrase_model = {}

    def _ensure_word_vectors(self):
        if self._word_vecs_norm is not None:
            return
        try:
            if os.path.exists(WV_PATH):
                vecs = np.load(WV_PATH)
                if os.path.exists(WV_VOCAB_PATH):
                    with open(WV_VOCAB_PATH, 'r', encoding='utf-8') as f:
                        self._word_vocab = json.load(f)
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self._word_vecs_norm = vecs / norms
            else:
                self._word_vecs_norm = np.array([])
        except Exception:
            self._word_vecs_norm = None
            self._word_vocab = {}

    def _ensure_ctx_index(self):
        if self._ctx_term_index is not None:
            return
        import jieba
        si_path = os.path.join(_PATHS['kb_json'], 'kb_search_index.json')
        idx_data = {}
        if os.path.exists(si_path):
            with open(si_path, 'r', encoding='utf-8') as f:
                idx_data = json.load(f).get('index', {})
        self._ctx_term_index = {}
        for fname, sections in idx_data.items():
            for sec in sections:
                h = sec.get('heading', '')
                h_tokens = set(t.strip() for t in jieba.lcut(h) if len(t.strip()) >= 2)
                for t in h_tokens:
                    if t not in self._ctx_term_index:
                        self._ctx_term_index[t] = set()
                    self._ctx_term_index[t].update(h_tokens)
        self._ctx_search_index = idx_data

    # ── CSR matrix builder ─────────────────────────────

    def _build_csr_matrix(self):
        edges = self._graph.get('edges', [])
        n_terms = self._graph.get('n_terms', 0)
        total = self._graph.get('total', 0)
        if not edges:
            return
        rows, cols, vals = [], [], []
        for i, row in enumerate(edges):
            if i >= n_terms:
                break
            for tgt, w in row:
                weight = w / 10000.0
                if tgt >= n_terms:
                    weight *= 2.0  # T→F edges boosted to compensate T→T density
                rows.append(i)
                cols.append(tgt)
                vals.append(weight)
        from scipy import sparse as _sp
        self._ppr_matrix = _sp.csr_matrix((vals, (rows, cols)), shape=(total, total))

    def _build_code_fid_map(self):
        files = self._graph.get('files', [])
        self._code_to_fid = {}
        for fi, fname in enumerate(files):
            code = _extract_code(fname)
            if code:
                nc = _normalize_code(code)
                if nc:
                    self._code_to_fid[nc] = fi

    # ── Lattice PPR seeds ──────────────────────────────

    def _lattice_seeds(self, query):
        """格PPR: 字符级图动态分词 + bigram条件概率 + 语境桥接

        对查询的所有2-7字符子串在词汇表中查找，构建字符格图。
        已知术语间用bigram条件概率加权，未知/弱术语通过语境桥接替换。
        """
        qlen = len(query)
        if qlen < 2:
            return None, None

        words = self._graph.get('words', [])
        w2id = self._w2id
        raw_edges = self._graph.get('edges', [])
        n_terms = self._graph.get('n_terms', 0)

        # Phase 1: 扫描所有子串 → 构建格图 + 分类已知/未知
        rows, cols, vals = [], [], []
        _edge_map = {}  # {(r,c): w} 避免 bigram 线性扫描
        known_terms = {}
        unknown_spans = []

        for i in range(qlen):
            for j in range(i + 2, min(i + 8, qlen + 1)):
                token = query[i:j]
                tid = w2id.get(token, -1)
                if tid >= 0:
                    file_deg = sum(1 for tgt, _ in raw_edges[tid]
                                   if tgt >= n_terms) if tid < n_terms else 0
                    base_w = np.log1p(5.0 / max(file_deg, 1))
                    # Bigram boost: P(next|prev) 条件概率
                    if i > 0:
                        for gap in [0, 1]:
                            target_end = i - gap
                            if target_end <= 0:
                                continue
                            for pi in range(max(0, target_end - 4), target_end):
                                found = False
                                if (pi, target_end) in _edge_map:
                                        prev_t = query[pi:target_end]
                                        p_src = self._bg_w2id.get(prev_t, -1)
                                        p_tgt = self._bg_w2id.get(token, -1)
                                        if p_src >= 0 and p_tgt >= 0:
                                            cp = self._bg_probs.get((p_src, p_tgt), 0)
                                            if cp > 0.003:
                                                base_w *= (1.0 + cp * 30)
                                                found = True
                                        break
                                if found:
                                    break
                            if found:
                                break
                    rows.append(i)
                    cols.append(j)
                    vals.append(base_w)
                    _edge_map[(i, j)] = base_w
                    known_terms[token] = tid
                else:
                    unknown_spans.append((i, j, token))

        # Phase 2: 语境桥接 — 已知强词→文件→标题词→匹配未知词
        term_scores = {}
        self._ensure_ctx_index()
        context_terms = set()
        strong_terms = {}
        weak_terms = {}

        for token, tid in known_terms.items():
            file_deg = sum(1 for tgt, _ in raw_edges[tid]
                           if tgt >= n_terms) if tid < n_terms else 0
            if file_deg >= 2:
                strong_terms[token] = (tid, file_deg)
            else:
                weak_terms[token] = (tid, file_deg)

        weak_spans = [(i, j, t) for i, j, t in unknown_spans]
        for token in weak_terms:
            for i in range(qlen):
                if query[i:i + len(token)] == token:
                    weak_spans.append((i, i + len(token), token))
                    break

        if strong_terms and weak_spans:
            # 使用术语索引: 每个强词 → 共现标题词
            for token in strong_terms:
                co_terms = self._ctx_term_index.get(token, set())
                context_terms.update(
                    ct for ct in co_terms
                    if ct in w2id and ct not in known_terms
                )
            # V2 语义邻居补充
            self._ensure_word_vectors()
            if self._word_vecs_norm is not None and len(self._word_vecs_norm) > 0:
                for token, (tid, _) in strong_terms.items():
                    if tid >= len(self._word_vecs_norm):
                        continue
                    sims = self._word_vecs_norm @ self._word_vecs_norm[tid]
                    for ni in np.argsort(-sims)[:5]:
                        if sims[ni] >= 0.6:
                            nw = words[ni] if ni < len(words) else ''
                            if nw and len(nw) >= 2:
                                context_terms.add(nw)

        # Phase 3: 匹配弱/未知跨度 → 语境术语
        for i, j, token in weak_spans:
            best_sim = 0.35
            best_term = None
            for ct in sorted(context_terms):  # v9.0: 定序遍历, 消除 set 受 hashseed 影响致并列时 best_term 跨进程不同
                if ct in known_terms:
                    continue
                shared = len(set(token) & set(ct))
                char_sim = shared / max(len(token), len(ct), 1)
                combined = char_sim
                if self._word_vecs_norm is not None and len(self._word_vecs_norm) > 0:
                    cid = w2id.get(ct, -1)
                    if cid >= 0:
                        for kt, (ktid, _) in strong_terms.items():
                            if ktid < len(self._word_vecs_norm) and cid < len(self._word_vecs_norm):
                                v2_sim = float(
                                    self._word_vecs_norm[ktid] @ self._word_vecs_norm[cid])
                                combined = char_sim * 0.3 + v2_sim * 0.7
                                if combined > best_sim:
                                    best_sim = combined
                                    best_term = ct
                            break
                elif char_sim > best_sim:
                    best_sim = char_sim
                    best_term = ct
            if best_term:
                cid = w2id.get(best_term, -1)
                if cid >= 0:
                    file_deg = (sum(1 for tgt, _ in raw_edges[cid]
                                    if tgt >= n_terms)
                                if cid < n_terms else 0)
                    replacement_weight = best_sim * 0.4
                    if file_deg >= 2:
                        replacement_weight *= 1.5
                    term_scores[best_term] = max(
                        term_scores.get(best_term, 0), replacement_weight)

        # Phase 4: 格PPR传播 → 边得分
        if not rows and not term_scores:
            return None, None

        lattice_ok = False
        if rows:
            from scipy import sparse as _sp
            adj = _sp.csr_matrix((vals, (rows, cols)), shape=(qlen + 1, qlen + 1))
            rowsum = np.array(adj.sum(1)).flatten()
            for i in range(qlen + 1):
                if rowsum[i] > 0:
                    adj.data[adj.indptr[i]:adj.indptr[i + 1]] /= rowsum[i]
            e = np.zeros(qlen + 1)
            e[0] = 1.0
            p = e.copy()
            for _ in range(20):
                p = 0.85 * e + 0.15 * (p @ adj)
            for i in range(qlen):
                if p[i] <= 0:
                    continue
                for idx in range(adj.indptr[i], adj.indptr[i + 1]):
                    j = adj.indices[idx]
                    token = query[i:j]
                    edge_score = float(p[i] * adj.data[idx])
                    if token in term_scores:
                        term_scores[token] = max(term_scores[token], edge_score)
                    else:
                        term_scores[token] = edge_score
            lattice_ok = True

        if not term_scores:
            return None, None

        # sqrt-inverse reweight: s^(-0.5) 温和反转保持区分度
        root_weights = {t: s ** (-0.5) for t, s in term_scores.items()}
        total_r = sum(root_weights.values())
        if total_r <= 0:
            return None, None
        normalized = {t: s / total_r for t, s in root_weights.items()}
        return normalized, lattice_ok

    # ── Seed vector builder ────────────────────────────

    def _build_seed_vector(self, query, term_extras=None, vector_boosts=None,
                           sentence_seeds=None, v2_neighbor_seeds=None):
        """多信号种子融合 → 统一 teleport 向量

        信号权重: 格PPR 75% + V2语义邻居 (0.4-0.8x) + 术语映射 0.5x + jieba补充 0.15x
        文件直投: 向量文件 10% + 句子向量文件 15%
        """
        import jieba

        n_terms = self._graph.get('n_terms', 0)
        total = self._graph.get('total', 0)
        words = self._graph.get('words', [])
        files = self._graph.get('files', [])

        self._ensure_phrase_model()

        # 格PPR 主种子
        lattice_seeds, lattice_ok = self._lattice_seeds(query)
        seed_weights = {}  # tid → weight

        if lattice_seeds:
            for token, score in lattice_seeds.items():
                tid = self._w2id.get(token, -1)
                if tid >= 0:
                    seed_weights[tid] = score
            # Jieba 低权重补充
            tokens = [t.strip() for t in jieba.lcut(query)
                      if len(t.strip()) >= 2 and t.strip() not in _NL_FILLERS]
            for t in tokens:
                tid = self._w2id.get(t, -1)
                if tid >= 0 and tid not in seed_weights:
                    seed_weights[tid] = 0.15
        else:
            # 格PPR完全失败 → jieba 回退
            tokens = [t.strip() for t in jieba.lcut(query)
                      if len(t.strip()) >= 2 and t.strip() not in _NL_FILLERS]
            for t in tokens:
                tid = self._w2id.get(t, -1)
                if tid >= 0:
                    seed_weights[tid] = 1.0

        # V2 语义邻居
        if v2_neighbor_seeds:
            v2_weight = 0.8 if not lattice_ok else 0.4
            for neighbor in v2_neighbor_seeds:
                tn = neighbor.strip()
                if len(tn) < 2 or tn in _NL_FILLERS:
                    continue
                nid = self._w2id.get(tn, -1)
                if nid >= 0 and nid not in seed_weights:
                    seed_weights[nid] = v2_weight

        # 术语映射扩展
        if term_extras:
            for extra in term_extras:
                et = [t.strip() for t in jieba.lcut(extra)
                      if len(t.strip()) >= 2 and t.strip() not in _NL_FILLERS]
                for t in et:
                    tid = self._w2id.get(t, -1)
                    if tid >= 0 and tid not in seed_weights:
                        seed_weights[tid] = 0.5

        # 向量 → 文件直投
        vec_file_seeds = {}
        if vector_boosts:
            for nc, sim in vector_boosts.items():
                fid = self._code_to_fid.get(nc, -1)
                if fid >= 0:
                    vec_file_seeds[fid] = sim

        # 句子向量 → 文件直投
        sent_file_seeds = {}
        if sentence_seeds:
            for ss in sentence_seeds:
                fname = ss.get('file', '')
                if hasattr(self, '_fname_to_fid') is False:
                    self._fname_to_fid = {f: i for i, f in enumerate(files)}
                if fname in files:
                    fid = self._fname_to_fid.get(fname, -1)
                    score = ss.get('sent_score', 0.5)
                    sent_file_seeds[fid] = max(sent_file_seeds.get(fid, 0), score)

        if not seed_weights and not vec_file_seeds and not sent_file_seeds:
            return None, lattice_ok

        # 构建 teleport 向量
        e = np.zeros(total, dtype=np.float64)
        n_vec, n_sent = len(vec_file_seeds), len(sent_file_seeds)

        total_w = sum(seed_weights.values())
        if total_w > 0:
            w_term_base = (0.75 if (n_vec or n_sent) else 1.0) / total_w
            for tid, mult in seed_weights.items():
                e[tid] = w_term_base * mult

        if n_vec > 0:
            w_vec = 0.10 / n_vec
            for fid, sim in vec_file_seeds.items():
                e[n_terms + fid] += w_vec * min(sim, 1.0)

        if n_sent > 0:
            w_sent = 0.15 / n_sent
            for fid, score in sent_file_seeds.items():
                e[n_terms + fid] += w_sent * min(score, 1.0)

        return e, lattice_ok

    # ── PPR propagation ────────────────────────────────

    def _propagate(self, e, alpha=0.85, iterations=5, lattice_ok=True,
                   reinforce_rounds=1):
        """CSR 稀疏 PPR 传播 + 交替强化 + 种子→文件直投预激活"""
        import jieba

        n_terms = self._graph.get('n_terms', 0)
        total = self._graph.get('total', 0)
        files = self._graph.get('files', [])
        edges = self._graph.get('edges', [])

        # Pre-activation: 种子术语有 T→F 边的, 将 teleport 直投文件节点
        # 解决大量技术术语 file_deg=0 导致 PPR 无法到达文件的问题
        seed_tids = [i for i in range(n_terms) if e[i] > 0]
        pre_injected = 0
        for tid in seed_tids:
            if tid < len(edges):
                for tgt, w in edges[tid]:
                    if tgt >= n_terms and e[tgt] == 0:
                        e[tgt] += e[tid] * 0.001  # 微量直投
                        pre_injected += 1
        if pre_injected > 0:
            e = e / e.sum()

        p = e.copy()
        for _ in range(iterations):
            p = alpha * e + (1 - alpha) * (p @ self._ppr_matrix)

        # 交替强化: top-5 文件反馈 → 种子增强 → 再传播
        if lattice_ok and reinforce_rounds > 0:
            seed_weights = {}
            for tid in range(n_terms):
                if e[tid] > 0:
                    seed_weights[tid] = e[tid]

            for rnd in range(reinforce_rounds):
                fp = p[n_terms:]
                top_indices = np.argsort(-fp)[:5]
                boosted = 0
                for fi in top_indices:
                    fname = files[int(fi)] if int(fi) < len(files) else ''
                    ftokens = set(t.strip() for t in jieba.lcut(fname)
                                  if len(t.strip()) >= 2)
                    for ft in ftokens:
                        tid = self._w2id.get(ft, -1)
                        if tid >= 0 and tid in seed_weights:
                            seed_weights[tid] = min(seed_weights[tid] * 1.5, 3.0)
                            boosted += 1
                if boosted > 0:
                    total_w_new = sum(seed_weights.values())
                    if total_w_new > 0:
                        for tid, mult in seed_weights.items():
                            e[tid] = mult / total_w_new
                    p = e.copy()
                    for _ in range(iterations):
                        p = alpha * e + (1 - alpha) * (p @ self._ppr_matrix)

        return p

    # ── Public API ─────────────────────────────────────

    def discover(self, query, term_extras=None, vector_boosts=None,
                 sentence_seeds=None, v2_neighbor_seeds=None,
                 project_standards=None, max_results=30,
                 existing_files=None):
        """PPR 图发现 — 返回候选文件列表

        Args:
            query: NL 技术查询字符串
            term_extras: 术语映射扩展词列表
            vector_boosts: {canonical_code: sim} 向量增强
            sentence_seeds: [{file, heading, sent_score}] 句子向量种子
            v2_neighbor_seeds: [term] V2 语义邻居词
            project_standards: set of standard codes (项目相关标准)
            max_results: 返回最大文件数 (过采样供 LLM 排序)
            existing_files: set of filenames to exclude
        """
        import time as _t
        t0 = _t.time()

        if not self._ensure_graph():
            return []

        # Build teleport vector
        e, lattice_ok = self._build_seed_vector(
            query, term_extras, vector_boosts, sentence_seeds, v2_neighbor_seeds
        )
        if e is None:
            return []

        # PPR propagation
        p = self._propagate(e, lattice_ok=lattice_ok)

        # Extract file scores
        n_terms = self._graph.get('n_terms', 0)
        files = self._graph.get('files', [])
        file_probs = p[n_terms:]
        mask = file_probs > 0.00001
        indices = np.where(mask)[0]

        existing = existing_files or set()
        results = []
        for i in indices:
            fname = files[int(i)] if int(i) < len(files) else ''
            if fname and fname not in existing:
                score = round(float(file_probs[i]) * 100000, 1)
                # Use filename as baseline text for downstream ranking
                display_name = os.path.splitext(fname)[0]
                results.append({
                    'file': fname,
                    'heading': display_name[:80],
                    'hits': 1,
                    'score': score,
                    'text': display_name[:200],
                    '_source': 'ppr_graph',
                })

        # v9.0: 加 file 名 tiebreaker —— 分数并列时按文件名定序, 吸收上游
        # set/dict 遍历受 PYTHONHASHSEED 随机化影响导致的跨进程顺序波动, 使结果可复现。
        results.sort(key=lambda x: (-x['score'], x.get('file', '')))
        elapsed = (_t.time() - t0) * 1000
        if elapsed > 100:
            import logging
            logging.info(f'PPR(engine): {len(results)} candidates in {elapsed:.0f}ms')

        return results[:max_results]

    def get_graph_stats(self):
        """返回图统计信息 (用于质量门)"""
        if not self._ensure_graph():
            return None
        return {
            'n_terms': self._graph.get('n_terms', 0),
            'n_files': self._graph.get('n_files', 0),
            'total_nodes': self._graph.get('total', 0),
            'edges': sum(len(row) for row in self._graph.get('edges', [])),
            'avg_out_degree': (
                sum(len(row) for row in self._graph.get('edges', [])) /
                max(self._graph.get('n_terms', 1), 1)
            ),
        }


# ── Utility functions (local copies to avoid circular imports) ──

def _normalize_code(raw):
    c = raw.strip().replace(' ', '').replace('-', '')
    c = c.replace('/T', 'T').replace('_T', 'T')
    return c


def _extract_code(text):
    m = re.search(
        r'((?:GB|JGJ|CJJ|CECS|CJ|DB|JTG|TCECS)(?:\d+)?\s*[/／]?\s*T?\s*[-]?\s*\d+[\.-]\d+(?:-\d+)?)',
        text
    )
    if m:
        return _normalize_code(m.group().replace('-', ''))
    return None


# ── Module-level singleton ─────────────────────────────

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = PPRDiscoveryEngine()
    return _engine


def discover(query, max_results=30, term_extras=None, vector_boosts=None,
             sentence_seeds=None, v2_neighbor_seeds=None, project_standards=None,
             existing_files=None):
    """便捷函数 — 单次 PPR 发现"""
    eng = get_engine()
    return eng.discover(
        query=query,
        max_results=max_results,
        term_extras=term_extras,
        vector_boosts=vector_boosts,
        sentence_seeds=sentence_seeds,
        v2_neighbor_seeds=v2_neighbor_seeds,
        project_standards=project_standards,
        existing_files=existing_files,
    )
