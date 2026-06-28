#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kb.py — 知识库统一访问层

规则（不可绕过）：
  1. kb.py 不 import 任何技能脚本（kb-update / construction-plan-writer）
  2. 两个技能只能通过 kb.py 访问知识库，禁止直接 import 对方
  3. kb.json 是所有路径的唯一真相源，任何脚本不得硬编码路径

用法：
  Python API:  from kb import KB, load_config
  CLI:         python kb.py status|search|read|check
"""
import os, re, sys, json

KB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(KB_DIR)
if KB_DIR not in sys.path:
    sys.path.insert(0, KB_DIR)

# ============================================================
# 配置加载
# ============================================================
def load_config():
    """从 kb.json 加载全部配置。这是所有脚本获取路径的唯一入口。"""
    cfg_path = os.path.join(KB_DIR, 'kb.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    # 路径统一解析为绝对路径，避免脚本受 cwd 影响。
    paths = cfg.get('paths', {})
    for k, v in list(paths.items()):
        if not isinstance(v, str):
            continue
        expanded = os.path.expanduser(v)
        paths[k] = expanded if os.path.isabs(expanded) else os.path.join(PROJECT_ROOT, expanded)
    return cfg

# ============================================================
# 规范编号规范化
# ============================================================
from kb_resolver_core import normalize_code, extract_code

# ============================================================
# KB 核心类
# ============================================================

# -- 查询词 → 专业分类标签推断表 (v6.11) --
# 基于 standard_tags.json 的 20 分类体系, 按技术关键词映射
_TAG_INFERENCE = {
    # 地基基础
    '基坑': ['地基基础'], '桩基': ['地基基础'], '桩': ['地基基础'],
    '地基': ['地基基础'], '回填': ['地基基础'], '压实': ['地基基础'],
    '换填': ['地基基础'], '挤密': ['地基基础'], '强夯': ['地基基础'],
    '地连墙': ['地基基础'], '地下连续墙': ['地基基础'],
    '支护': ['地基基础'], '锚杆': ['地基基础'], '土钉': ['地基基础'],
    '勘察': ['地基基础'], '复合地基': ['地基基础'], '监测': ['地基基础'],

    # 混凝土结构
    '混凝土': ['混凝土结构'], '模板': ['混凝土结构'],
    '预应力': ['混凝土结构'], '灌浆': ['混凝土结构'],
    '大体积混凝土': ['混凝土结构'], '养护': ['混凝土结构'],
    '保护层': ['混凝土结构'], '预埋': ['混凝土结构'],

    # 砌体结构
    '砌体': ['砌体结构'], '砌块': ['砌体结构'], '砖': ['砌体结构'],
    '砂浆': ['砌体结构'],

    # 铺装地面
    '铺装': ['铺装地面'], '地面': ['铺装地面'], '防碱': ['铺装地面'],
    '背涂': ['铺装地面'], '石材': ['铺装地面'], '地坪': ['铺装地面'],
    '花岗岩': ['铺装地面'], '大理石': ['铺装地面'],

    # 电气
    '电缆': ['电气'], '配电': ['电气'], '桥架': ['电气'],
    '电气': ['电气'], '照明': ['电气'], '防雷': ['电气'],
    '接地': ['电气'], '绝缘': ['电气'],

    # 给排水
    '管道': ['给排水'], '给水': ['给排水'], '排水': ['给排水'],
    '检查井': ['给排水'], '排水管': ['给排水'], '给水管': ['给排水'],
    '水压': ['给排水'], '闭水': ['给排水'], '化粪池': ['给排水'],
    '卫生间': ['给排水', '屋面防水'],

    # 园林绿化
    '园林': ['园林绿化'], '绿化': ['园林绿化'], '种植': ['园林绿化'],
    '苗木': ['园林绿化'], '草坪': ['园林绿化'], '花坛': ['园林绿化'],
    '种植土': ['园林绿化'], '移植': ['园林绿化'],

    # 施工安全
    '脚手架': ['施工安全'], '安全': ['施工安全'], '围挡': ['施工安全'],
    '高处作业': ['施工安全'], '临时用电': ['施工安全'], '塔吊': ['施工安全'],
    '起重': ['施工安全'], '吊装': ['施工安全'], '防护': ['施工安全'],
    '卸料平台': ['施工安全'], '安全网': ['施工安全'],
    '消防': ['施工安全'], '防火': ['施工安全'],

    # 质量验收
    '验收': ['质量验收'], '检验': ['质量验收'],

    # 钢结构
    '钢结构': ['钢结构'], '焊接': ['钢结构'], '高强螺栓': ['钢结构'],
    '焊缝': ['钢结构'], '探伤': ['钢结构'],

    # 屋面防水
    '屋面': ['屋面防水'], '防水': ['屋面防水'], '卷材': ['屋面防水'],
    '涂膜': ['屋面防水'], '渗漏': ['屋面防水'], '保温': ['屋面防水'],

    # 幕墙装饰
    '幕墙': ['幕墙装饰'], '装饰': ['幕墙装饰'], '装修': ['幕墙装饰'],
    '抹灰': ['幕墙装饰'], '涂饰': ['幕墙装饰'], '吊顶': ['幕墙装饰'],
    '门窗': ['幕墙装饰'],

    # 暖通空调
    '暖通': ['暖通空调'], '空调': ['暖通空调'], '通风': ['暖通空调'],
    '风管': ['暖通空调'], '防排烟': ['暖通空调'], '排烟': ['暖通空调'],

    # 轨道交通
    '轨道交通': ['轨道交通'], '地铁': ['轨道交通'], '盾构': ['轨道交通'],
    '轨道': ['轨道交通'],

    # 城市道路
    '道路': ['城市道路'], '路基': ['城市道路'], '路面': ['城市道路'],
    '路桥': ['城市道路'], '桥梁': ['城市道路'],

    # 设计通用
    '抗震': ['设计通用'], '荷载': ['设计通用'], '结构设计': ['设计通用'],

    # 材料标准
    '管材': ['材料标准'], '混凝土制品': ['材料标准'],

    # 环境噪声
    '噪声': ['环境噪声'], '扬尘': ['环境噪声'], '废弃物': ['环境噪声'],
    '振动': ['环境噪声'],
}


def _annotate_coverage(results, query):
    """消费端覆盖度标注: 用术语索引比对每个结果和问题的内容交集。
    不改搜索排序 — 只将覆盖度写入结果的 _coverage 字段供消费者决策。
    """
    import os as _os, json as _json, re as _re

    # 加载术语索引
    paths = load_config().get('paths', {})
    idx_path = paths.get('kb_term_map')
    ti_path = paths.get('kb_term_index')

    if not _os.path.exists(idx_path) or not _os.path.exists(ti_path):
        return

    with open(idx_path, 'r', encoding='utf-8') as f:
        term_map = _json.load(f)
    with open(ti_path, 'r', encoding='utf-8') as f:
        ti = _json.load(f)

    # 已知术语
    known = set(term_map.keys())
    for vs in term_map.values():
        for v in vs:
            if len(v) >= 2: known.add(v)

    # 提取问题中的有效术语
    q_terms = set()
    for wlen in [2, 3, 4]:
        for i in range(len(query) - wlen + 1):
            w = query[i:i+wlen]
            if w in known:
                q_terms.add(w)
    if len(q_terms) < 2:
        return

    # 术语索引 → {文件 → 术语集合}
    index = ti.get('index', {})
    files_list = ti.get('_files', [])
    file_terms_map = {}
    for term, entries in index.items():
        if term not in q_terms:
            continue
        for entry in entries:
            if isinstance(entry, list) and len(entry) >= 2:
                fid = entry[0]
                if fid < len(files_list):
                    fname = files_list[fid]
                    if fname not in file_terms_map:
                        file_terms_map[fname] = set()
                    file_terms_map[fname].add(term)

    # 标注每个结果
    for r in results:
        fname = r.get('file', '')
        if '(vector' in fname:
            r['_coverage'] = None
            continue
        matched = file_terms_map.get(fname, set())
        r['_coverage'] = round(len(matched) / len(q_terms), 2) if q_terms else None


def _infer_prefer_tags(query):
    """根据查询词自动推断应激活的专业分类标签。

    仅当 prefer 参数未显式传入时调用。
    推断策略: 查询词命中 _TAG_INFERENCE 表中的关键词 → 收集对应标签。
    多个关键词命中同一标签 → 该标签得分加权 (出现次数越多, 越可能激活)。
    最多返回 3 个区分度最高的标签。

    Returns:
        list[str] 或 None (无法推断时返回 None, 不做任何 boost)
    """
    if not query or len(query.strip()) < 1:
        return None

    q = query.lower()
    tag_scores = {}
    for keyword, tags in _TAG_INFERENCE.items():
        if keyword.lower() in q:
            for t in tags:
                tag_scores[t] = tag_scores.get(t, 0) + 1

    if not tag_scores:
        return None

    # 按得分排序, 取 top 3
    ranked = sorted(tag_scores.items(), key=lambda x: -x[1])
    # 过滤: 得分太低的不激活
    ranked = [(t, s) for t, s in ranked if s >= 1]
    if not ranked:
        return None

    return [t for t, s in ranked[:3]]


class KB:
    def __init__(self):
        self.cfg = load_config()
        self.P = self.cfg['paths']
        self._resolver = None

    # ---- 内部: 惰性加载底层实现 ----
    def _get_resolver(self):
        """惰性加载 KBResolver 核心实现"""
        if self._resolver is not None:
            return self._resolver
        import importlib.util
        core_path = os.path.join(KB_DIR, 'kb_resolver_core.py')
        spec = importlib.util.spec_from_file_location('kb_resolver_core', core_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._resolver = mod.KBResolver()
        return self._resolver

    # ================================================================
    # 公开 API
    # ================================================================

    def status(self):
        """KB 全景快照 —— AI 第一轮必调"""
        r = self._get_resolver()
        s = r.stats()
        # 类别分布
        try:
            tag_path = self.P.get('standard_tags', '')  # contracts/ 经 kb.json 寻址
            if tag_path and os.path.exists(tag_path):
                with open(tag_path, 'r', encoding='utf-8') as f:
                    tags = json.load(f)
                categories = {k: len(v) if isinstance(v, list) else 0
                             for k, v in tags.items() if not k.startswith('_')}
            else:
                categories = {}
        except Exception:
            categories = {}

        result = {
            'standards': s['standards_in_index'],
            'clauses': s['indexed_clauses'],
            'md_files': s['md_files'],
            'md_with_codes': s['md_with_codes'],
            'search_sections': self._count_search_sections(),
            'search_mode': self.cfg['search']['default_mode'],
            'vector_weight': self.cfg['search']['default_vector_weight'],
            'categories': categories,
        }
        try:
            import metrics
            metrics.record_status(result['standards'], result['clauses'],
                                result['md_files'])
        except ImportError:
            pass
        return result

    def _count_search_sections(self):
        # Resolve relative paths from kb.json relative to project root (not CWD)
        kb_json_rel = self.P.get('kb_json', self.P['kb_md'])
        if not os.path.isabs(kb_json_rel):
            si_path = os.path.join(os.path.dirname(KB_DIR), kb_json_rel, 'kb_search_index.json')
        else:
            si_path = os.path.join(kb_json_rel, 'kb_search_index.json')
        if os.path.exists(si_path):
            try:
                with open(si_path, 'r', encoding='utf-8') as f:
                    si = json.load(f)
                return sum(len(v) for v in si.get('index', {}).values())
            except Exception:
                pass
        return 0

    def search(self, query, max_results=None, vector_weight=None, project_standards=None,
               must=None, must_not=None, prefer=None, support_guard=False,
               support_guard_mode=None, support_truth_path=None):
        """
        混合搜索（关键词 + BGE-M3 向量）+ Bool 过滤 + 标签偏好。

        Args:
            query: 搜索查询（SHOULD 语义——匹配到的加分）
            max_results: 最大结果数
            vector_weight: 向量权重 0-1
            project_standards: 项目规范集合（排序提升）
            must: 文档级硬过滤——文件必须包含全部 MUST 词
            must_not: 文档级排除——文件包含任一词则跳过
            prefer: 标签偏好列表——命中文件 score×1.5 (不丢结果，仅加分)
                    None 时自动根据查询词推断 (v6.11)
            support_guard: 可选真实性支撑诊断。默认关闭，不改变旧查询行为。
            support_guard_mode: 'annotate'(默认) 只加诊断字段；'rerank' 按支撑度保守重排。
            support_truth_path: truth jsonl 路径；默认使用 kb.json 中的 search.support_guard.truth_path。
        """
        r = self._get_resolver()
        mr = max_results or self.cfg['search']['max_results']

        # v6.18: "image:" 前缀路由到图片专用搜索
        if query.startswith('image:'):
            img_query = query[6:].strip()
            img_results = r.search_images(img_query, max_results=mr)
            # 转换为统一格式，保留 code 字段供质量门提取
            results = []
            for ir in img_results:
                results.append({
                    'file': ir.get('file', ''),
                    'heading': ir.get('section', ''),
                    'hits': ir.get('score', 1),
                    'score': ir.get('score', 1) * 10,
                    'text': ir.get('context', '')[:200],
                    '_source': 'image_search',
                    'code': ir.get('code', ''),
                    'image': ir.get('image', ''),
                })
            return results[:mr]

        vw = vector_weight if vector_weight is not None else self.cfg['search']['default_vector_weight']

        # 自动推断 prefer 标签 (v6.11)
        if prefer is None:
            prefer = _infer_prefer_tags(query)

        import time as _time
        t0 = _time.time()
        results = r.search(query, max_results=mr, vector_weight=vw, project_standards=project_standards,
                          must=must, must_not=must_not, prefer=prefer)
        if support_guard:
            try:
                from support_guard import annotate_results
                guard_cfg = self.cfg.get('search', {}).get('support_guard', {})
                mode = support_guard_mode or guard_cfg.get('mode', 'annotate')
                truth_path = support_truth_path or guard_cfg.get('truth_path', 'eval/truth_queries_seed.jsonl')
                if not os.path.isabs(truth_path):
                    truth_path = os.path.join(PROJECT_ROOT, truth_path)
                top_k = int(guard_cfg.get('top_k', mr) or mr)
                results = annotate_results(query, results, truth_path, mode=mode, top_k=top_k)
            except Exception as exc:
                for item in results:
                    item.setdefault('support_guard', {'error': f'{type(exc).__name__}: {exc}'})
        elapsed = (_time.time() - t0) * 1000
        if elapsed > 1500:
            print(f'  [WARN] 搜索超时: {elapsed:.0f}ms (query={query[:40]})')
        try:
            import metrics
            metrics.record_search(query, elapsed, len(results),
                                'hybrid' if vw > 0 else 'keyword')
        except ImportError:
            pass
        # 搜索日志: 追加查询→文件码映射 (供浮动标签评分)
        if results and len(query.strip()) > 1:
            try:
                import re as _re, json as _json, os as _os
                log_path = _os.path.join(_os.path.dirname(__file__), '..', 'pipeline', 'kb_search_log.jsonl')
                import time as _t
                codes = set()
                for r in results[:10]:
                    m = _re.search(r'(GB|JGJ|CJJ|CECS|DB|JTG|TCECS)[\sT/\d\.\-]+', r.get('file', ''))
                    if m:
                        c = m.group(0).replace(' ', '').replace('/','')
                        c = _re.sub(r'-20\d{2}.*$', '', c)  # 去年份, 和tag_scorer格式匹配
                        codes.add(c)
                if codes:
                    entry = {'ts': _t.strftime('%Y-%m-%dT%H:%M:%S'), 'q': query, 'c': list(codes)[:5]}
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(_json.dumps(entry, ensure_ascii=False) + '\n')
            except Exception:
                pass  # 静默: 日志不影响搜索功能
            # v6.16: 自适应候选池 (TODO: 等待反馈闭环消费 kb_feedback.jsonl 数据后激活晋升逻辑)
            try:
                kw_count = sum(1 for r in results if '(vector match)' not in r.get('file', ''))
                vec_count = sum(1 for r in results if '(vector match)' in r.get('file', ''))
                if kw_count < 3 and vec_count > 0:
                    import re as _re, json as _json, os as _os
                    # 提取2-4字中文词, 筛掉停用词和映射表中已有词
                    from kb_resolver_core import _load_term_map
                    known = set(_load_term_map().keys()) if _load_term_map() else set()
                    unknown_words = []
                    for w in _re.findall(r'[\u4e00-\u9fff]{2,4}', query):
                        if w not in known and w not in {'要求','标准','规范','施工','工程','问题','原因','处理','分析','方法'}:
                            unknown_words.append(w)
                    if unknown_words:
                        cand_path = _os.path.join(_os.path.dirname(__file__), '..', 'pipeline', 'kb_term_candidates.json')
                        candidates = {}
                        if _os.path.exists(cand_path):
                            with open(cand_path, 'r', encoding='utf-8') as cf:
                                candidates = _json.load(cf)
                        for uw in unknown_words:
                            if uw not in candidates:
                                candidates[uw] = {'files': [], 'queries': 0, 'first': _time.strftime('%Y-%m-%d')}
                            candidates[uw]['queries'] += 1
                            for r in results[:5]:
                                fn = r.get('file', '').replace('(vector match)', '').strip().lstrip('[').rstrip(']')
                                if fn and fn not in candidates[uw]['files']:
                                    candidates[uw]['files'].append(fn[:60])
                        with open(cand_path, 'w', encoding='utf-8') as cf:
                            _json.dump(candidates, cf, ensure_ascii=False, indent=2)
            except Exception:
                pass
            # v6.17: 消费端覆盖度标注 — 用术语索引比对结果与问题的内容交集
            if results and len(query.strip()) > 4:
                try:
                    _annotate_coverage(results, query)
                except Exception:
                    pass
        return results

    def resolve_clause(self, query, standard_code=None, max_results=8):
        """三层收敛一键回答: 搜索→锁定规范→提取条款号→精读原文 (v6.18重写)

        条款号提取策略 (按优先级):
          1. 搜索结果 heading 中的条款号 (如 "8.2.3 构造柱")
          2. 搜索结果的 text body 中第一个条款号模式
          3. 直接用 code 读规范 → 从正文提取最相关的条款号
        """
        import re as _re
        results = self.search(query, max_results=max_results, vector_weight=0.4)
        if not results:
            return None

        # 步骤1: 锁定规范
        code = standard_code
        if not code:
            for r in results:
                code = extract_code(r.get('file', ''))
                if code:
                    m = _re.match(r'^(.+?)(19[5-9]\d|20[0-9]\d)$', code.replace(' ','').replace('-',''))
                    code = m.group(1) if m else code.replace(' ','').replace('-','')
                    break

        # 步骤2: 提取条款号 (多策略)
        clause = None
        _SKIP = {'一般规定','基本要求','术语','符号','总则','目次','前言'}

        # 策略A: 从 heading 提取
        for r in results:
            h = r.get('heading', '').strip()
            if any(h == s or h.startswith(s) for s in _SKIP): continue
            if not _re.search(r'[\u4e00-\u9fff\d]', h): continue
            # 匹配条款号: "8.2.3", "4.2", "B.1", "Ⅱ", "一、"
            m = _re.search(r'(?:\d+(?:\.\d+)+|[A-Z]\.\d+|[Ⅰ-Ⅻ]+|[一二三四五六七八九十]+[、．.])', h)
            if m:
                clause = m.group(0).rstrip('、．.')
                break

        # 策略B: 从正文 body 提取条款号
        if not clause:
            for r in results[:3]:
                body = r.get('text', '')[:2000]
                # 优先匹配 "X.X.X" 条款号模式
                m = _re.search(r'(?:^|\n)\s*(\d+(?:\.\d+)+)\s', body, _re.MULTILINE)
                if m:
                    clause = m.group(1)
                    break
                # 回退: "第X条" 模式
                m = _re.search(r'第\s*(\d+(?:\.\d+)*)\s*条', body)
                if m:
                    clause = m.group(1)
                    break

        # 策略C: 直接用 code 读规范, 从开头正文找最相关的条款号
        if not clause and code:
            text = self.read_clause(code, '1')
            if text and len(text) > 100:
                # 找到第一个条款号模式
                m = _re.search(r'(?:^|\n)\s*(\d+(?:\.\d+)+)\s', text[:2000], _re.MULTILINE)
                if m:
                    clause = m.group(1)

        if not code or not clause:
            return None

        name, _, _ = self.get_name(code)
        text = self.read_clause(code, clause)
        if not text:
            return None

        return {'code': code, 'name': name, 'clause': clause, 'text': text}

    def search_images(self, query, max_results=10):
        """搜索知识库中的图片 (v6.18)。

        匹配查询词与图片所在章节标题及前后文段。
        返回包含图片路径、规范号、章节、上下文的结果列表。
        """
        r = self._get_resolver()
        return r.search_images(query, max_results=max_results)

    def feedback(self, entry):
        """记录消费端反馈 (v6.20)。

        entry 字段:
          type: 'search_click' | 'clause_cite' | 'zero_result' | 'term_match' | 'image_used'
          query: 原始查询词
          result_used: {code, section, score, rank}  (可选)
          clause_cited: 最终引用的条款号 (可选)
          terms_matched: 匹配到的术语列表 (可选)
          ai_fallback: AI 是否需要自己补充判断 (可选)

        反馈记录到 kb_feedback.jsonl, 用于驱动术语表扩充、标签优化、搜索改进。
        """
        self._get_resolver().record_feedback(entry)

    def read_clause(self, standard_code, clause_pattern, prefer_type=None):
        """读取条款原文（含表格/公式，自动交叉引用解析）。
        prefer_type: None(正文优先) | 'normative' | 'commentary' | 'appendix' | 'any'
        """
        return self._get_resolver().read_clause(standard_code, clause_pattern, prefer_type)

    def read_clause_full(self, standard_code, clause_pattern, prefer_type=None):
        """v6.18: 读取条款原文 + 类型信息 + 备选版本。
        返回 {text, type, alternatives: [{type, heading}]}
        type: normative | commentary | appendix | unknown
        alternatives: 同条款号的其他类型版本, 调用方可据此判断是否需要补充查条文说明
        """
        return self._get_resolver().read_clause_full(standard_code, clause_pattern, prefer_type)

    def check(self, *codes):
        """批量检查规范是否在知识库中。返回 {code: bool}"""
        r = self._get_resolver()
        result = {}
        for code in codes:
            result[code] = r.exists(code)
        return result

    def find_md(self, standard_code):
        """查找规范对应的 MD 文件路径"""
        return self._get_resolver().find_md(standard_code)

    def read_md(self, standard_code):
        """读取规范的完整 MD 内容（用于 Read 工具替代）"""
        path = self.find_md(standard_code)
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        return None

    def get_name(self, standard_code):
        """三层回退解析规范编号→中文名称。返回 (name, layer, confidence)"""
        return self._get_resolver().get_name(standard_code)

    def exists(self, standard_code):
        """检查单部规范是否在知识库中"""
        return self._get_resolver().exists(standard_code)

    def get_clause_count(self, standard_code):
        """获取规范的索引条款数"""
        return self._get_resolver().get_clause_count(standard_code)

    def list_unused(self, cited_codes, keyword_filter=None):
        """列出知识库中有但方案未引用的规范"""
        return self._get_resolver().list_unused(cited_codes, keyword_filter=keyword_filter)

    def find_all_md(self, standard_code):
        """查找规范的所有 MD 文件（含分段文件）"""
        return self._get_resolver().find_all_md(standard_code)


# ============================================================
# CLI
# ============================================================
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    kb = KB()

    if len(sys.argv) < 2:
        print("用法: python kb.py status|search|read|check|name|metrics|self-test")
        print("  status          全景快照 (JSON)")
        print("  search <query>   混合搜索")
        print("  read <code> <§>  读取条款")
        print("  check <code...>  批量存在性检查")
        print("  name <code...>   规范编号→中文名称（三层回退）")
        print("  self-test        当前模块自检")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == 'status':
        print(json.dumps(kb.status(), ensure_ascii=False, indent=2))

    elif cmd == 'search':
        query = ' '.join(sys.argv[2:])
        results = kb.search(query)
        if not results:
            print(f'(无结果: {query})')
        for i, r in enumerate(results):
            print(f"\n[{i+1}] {r['file'][:50]} | s={r.get('score','?')}"
                  f"{' | vs='+str(r.get('vector_sim','')) if r.get('vector_sim') else ''}"
                  f"\n  {r['heading'][:60]}\n  {r['text'][:200]}")

    elif cmd == 'read':
        code, clause = sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ''
        text = kb.read_clause(code, clause) if clause else kb.read_md(code)
        if text:
            print(text[:5000])
        else:
            print(f'{code}: 未找到')

    elif cmd == 'metrics':
        sub = sys.argv[2] if len(sys.argv) > 2 else 'search'
        try:
            import metrics
        except ImportError:
            print('metrics module not available')
            sys.exit(1)
        if sub == 'search':
            s = metrics.search_stats(50)
            print(json.dumps(s, ensure_ascii=False, indent=2))
        elif sub == 'status':
            h = metrics.status_history(20)
            for e in h:
                print(json.dumps(e, ensure_ascii=False))
        else:
            print('Usage: python kb.py metrics search|status')

    elif cmd == 'check':
        results = kb.check(*sys.argv[2:])
        for code, exists in results.items():
            print(f'{code}: {"IN KB" if exists else "NOT FOUND"}')

    elif cmd == 'name':
        for code in sys.argv[2:]:
            name, layer, confidence = kb.get_name(code)
            if name:
                print(f'{code}: {name} (L{layer}, {confidence})')
            else:
                print(f'{code}: NOT FOUND')

    elif cmd == 'self-test':
        """新增能力自带自检——覆盖当前模块关键路径"""
        errors = 0
        # 1. get_name 基本功能
        for code, kw in [('GB50209', '建筑地面'), ('JGJ79', '地基处理'),
                         ('CJJ82', '园林绿化'), ('CECS453', '轻质泡沫土'),
                         ('GBT10801.1', 'EPS')]:
            n, l, c = kb.get_name(code)
            if not n or kw not in n:
                print(f'  FAIL get_name({code}): got={n}')
                errors += 1
        # 2. 不存在规范
        n, _, _ = kb.get_name('GB99999')
        if n is not None:
            print(f'  FAIL get_name(GB99999): should be None, got={n}')
            errors += 1
        # 3. GBT/GB 等价
        n, _, _ = kb.get_name('GB50720')
        if not n or '消防' not in n:
            print(f'  FAIL GBT/GB equiv: got={n}')
            errors += 1
        # 4. check 批量
        results = kb.check('GB50209', 'JGJ79', 'GB99999')
        if not results.get('GB50209') or not results.get('JGJ79') or results.get('GB99999'):
            print(f'  FAIL check: {results}')
            errors += 1
        # 5. v6.24: 搜索端到端
        r_e2e = kb.search('混凝土强度等级', max_results=5)
        if len(r_e2e) < 2:
            print(f'  FAIL search+rerank: only {len(r_e2e)} results')
            errors += 1
        else:
            print(f'  PASS search+rerank: {len(r_e2e)} results')

        if errors:
            print(f'\n{errors} FAILURES')
            sys.exit(1)
        else:
            print('ALL SELF-TESTS PASSED')
