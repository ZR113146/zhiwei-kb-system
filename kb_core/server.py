# -*- coding: utf-8 -*-
"""知微 KB v3 — 搜索 + 条款浏览"""
import sys, os, re, time, json
_KB_DIR = os.path.dirname(os.path.abspath(__file__))
if _KB_DIR not in sys.path: sys.path.insert(0, _KB_DIR)

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="知微 KB")

# CORS: allow Obsidian Electron and local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # allow_credentials removed (conflicts with allow_origins=*)
    allow_methods=["*"],
    allow_headers=["*"],
)
_kb = None
def get_kb():
    global _kb
    if _kb is None:
        from kb_core.kb import KB; _kb = KB()
    return _kb

# ===== Helpers =====

# Paths from kb.json (project-relative, Codex platform)
from kb_core.kb import load_config
_PATHS = load_config().get('paths', {})
_ROOT_DIR = os.path.dirname(_KB_DIR)
_KB_JSON_DIR = _PATHS['kb_json']
KB_DIR = _PATHS['kb_md']
CI_PATH = os.path.join(_KB_JSON_DIR, "kb_clause_index.json")

# 自动补全索引 (启动时构建)
_suggest_cache = []
def _build_suggest_index():
    global _suggest_cache
    si_path = os.path.join(_KB_JSON_DIR, 'kb_search_index.json')
    if not os.path.exists(si_path): return
    with open(si_path, 'r', encoding='utf-8') as f:
        si = json.load(f)
    idx = si.get('index', {})
    seen = set()
    for fname, sections in idx.items():
        name = fname.replace('.md', '')
        for seg in ['_seg0_', '_seg1_', '_seg2_', '_seg3_']:
            name = name.replace(seg, '')
        name = re.sub(r'_p\d{4}-\d{4}', '', name).strip()
        if name and name not in seen:
            seen.add(name)
            _suggest_cache.append({'text': name, 'type': 'standard', 'file': fname})
        for sec in sections:
            h = sec.get('heading', '').strip()
            if h and len(h) >= 2 and h not in seen:
                seen.add(h)
                _suggest_cache.append({'text': h, 'type': 'clause', 'file': fname})

def _extract_clause_text(text, pos, length, clause):
    """提取条款文本: pos+length 切片, 短内容 (<200 chars) 时前向行扫描"""
    raw = text[pos:pos+min(length, 5000)]
    if len(raw) >= 200:
        return raw
    # 前向行扫描: 读取到下一同级/上级标题为止
    suffix = text[pos:min(len(text), pos+4000)]
    lines = suffix.split('\n')
    heading_pat = re.compile(r'^#*\s*(?:\d+(?:\.\d+)*|[IVXLCDM\u2160-\u217B]+)\s+\S')
    collected = []
    started = False
    for i, ln in enumerate(lines):
        if not started and ln.strip() and not ln.startswith('#'):
            started = True
        if started and i > 0 and ln.strip():
            m = heading_pat.match(ln)
            if m:
                hdr_text = m.group(0).lstrip('#').strip()
                hdr_num = hdr_text.split()[0] if hdr_text.split() else ''
                if hdr_num and hdr_num != clause:
                    break
        collected.append(ln)
    result = '\n'.join(collected).strip()
    if len(result) > 80:
        return result[:5000]
    # 仍然太短 → 取 pos 后 3000 字符, 但在下一个 ## 标题处截断
    chunk = text[pos:min(len(text), pos+3000)]
    next_h2 = re.search(r'\n##\s', chunk)
    if next_h2:
        chunk = chunk[:next_h2.start()]
    return chunk.strip()[:5000]

def load_clause_index():
    return json.load(open(CI_PATH,'r',encoding='utf-8')) if os.path.exists(CI_PATH) else None


def _query_units(query: str):
    """把查询切成有意义的覆盖单元 (用于度量结果对查询的内容覆盖)。

    返回 [(unit, weight)]: 拉丁/编码 token 各算一个单元; 每段中文连写算一个单元。
    不再把长中文串切成重叠 n-gram 当独立单元 — 那会让重叠片段 (混凝/凝土/混凝土)
    被算成多次命中, 系统性虚高覆盖率。中文段的部分命中改由 _coverage 内按字符占比计。"""
    text = (query or '').strip().lower()
    units = []
    for tok in re.findall(r'[a-z]+\d*(?:[./_-]?\d+)*', text):
        if len(tok) >= 2:
            units.append((tok, 2.0 if len(tok) >= 4 else 1.0))
    for run in re.findall(r'[一-鿿]{2,}', text):
        units.append((run, 2.0 if len(run) >= 4 else 1.0))
    seen = []
    seen_set = set()
    for unit, weight in units:
        if unit not in seen_set:
            seen_set.add(unit)
            seen.append((unit, weight))
    return seen[:12]

_CN_STOP = set('规范标准技术工程施工设计验收要求规定有关进行采用应按以及和的与中及')

def _run_match_fraction(run: str, body_text: str):
    """中文段对正文的覆盖占比 (0-1)。整段命中=1.0; 否则按命中字符占比, 用 2/3-gram 探测
    并去重叠 — 度量\"查询里多少内容真出现在结果\", 而非命中次数。"""
    if run in body_text:
        return 1.0
    if len(run) < 4:
        return 0.0
    covered = [False] * len(run)
    for size in (3, 2):
        for i in range(0, len(run) - size + 1):
            piece = run[i:i + size]
            if all(ch in _CN_STOP for ch in piece):
                continue
            if piece in body_text:
                for j in range(i, i + size):
                    covered[j] = True
    return sum(covered) / len(run)

def _coverage(query: str, result: dict):
    units = _query_units(query)
    if not units:
        return 0.0, 0, 0, []
    title_text = f"{result.get('file','')} {result.get('heading','')}".lower()
    body_text = f"{title_text} {result.get('text','')}".lower()
    matched = []
    weighted_total = 0.0
    weighted_match = 0.0
    title_hits = 0
    for unit, weight in units:
        weighted_total += weight
        is_cn = bool(re.match(r'[一-鿿]', unit))
        frac = _run_match_fraction(unit, body_text) if is_cn else (1.0 if unit in body_text else 0.0)
        if frac > 0:
            weighted_match += weight * frac
            if frac >= 0.5:
                matched.append(unit)
            if unit in title_text:
                title_hits += 1
    return (weighted_match / weighted_total if weighted_total else 0.0), len(matched), title_hits, matched[:6]

# 绝对分数→可信度档位。与 resolver._assign_confidence 同口径 (high>=60 / mid>=20)。
_SCORE_BANDS = (('high', 60.0), ('mid', 20.0))

def _band_from_score(score: float):
    for label, threshold in _SCORE_BANDS:
        if score >= threshold:
            return label
    return 'low'

def _confidence(query: str, result: dict):
    """绝对可信度: 以最终分数档位为基准, 覆盖率仅作单向降级 (降一档)。

    'high' 表示\"这条答案可靠\", 而非\"本次结果里相对最好\" — 后者 (旧的 score/best_score
    曲线) 会让弱查询的 top 结果恒判高。
    - 基准档直接按 server 收到的最终 score 算, 不复用 resolver 的 confidence 字段:
      resolver 在 authority boost 之前赋档, 与 boost 后的最终分可能错位 (编码查询尤甚)。
    - 覆盖率门只降一档 (high->mid, mid->low), 不直接砸到 low: 高分是检索引擎的强命中信号,
      字面零覆盖多为同义召回 (\"开裂\"vs\"裂缝\"), 只提示\"需核对\"而非判不可信。
    - 精确命中 (条款/文件名直达) 覆盖率天然偏低, 豁免覆盖率门。"""
    score = float(result.get('score') or 0)
    coverage, match_count, title_hits, matched = _coverage(query, result)
    label = _band_from_score(score)
    source = result.get('_source', '')
    trace = result.get('_trace') or {}
    branch = trace.get('branch', '')
    exactish = source in {'clause_index', 'filename_title'} or branch in {'direct', 'filename_title'}
    if not exactish and coverage < 0.15:
        # 字面几乎没对上 -> 降一档 (强检索信号仍保留, 但提示需人工核对)
        label = 'mid' if label == 'high' else 'low'
    return label, {
        'query_coverage': round(coverage, 2),
        'matched_terms': matched,
        'title_hits': title_hits,
        'score_band': _band_from_score(score),
    }

# ===== API =====

class SearchRequest(BaseModel):
    query: str
    max_results: int = 10

@app.post("/api/search")
def api_search(req: SearchRequest):
    kb = get_kb(); t0 = time.time()
    results = kb.search(req.query, max_results=req.max_results)
    elapsed = int((time.time()-t0)*1000)
    items = []
    for idx, r in enumerate(results, start=1):
        m = re.search(r'(GB|JGJ|CJJ|CECS|TCECS|DB\d*|CJ|JTG|JTJ|TB|DL|SL|SH|SY|HG|YB|JG|SB)[\sT/_]?(\d+(?:\.\d+)?(?:-\d+)?)', r.get('file',''))
        code = (m.group(1)+m.group(2)).replace(' ','').replace('_','/') if m else ''
        trace = r.get('_trace') or {}
        route = trace.get('branch') or r.get('_source','search')
        if trace.get('reason'):
            route = f"{route}:{trace.get('reason')}"
        score = round(r.get('score',0),1)
        confidence, confidence_meta = _confidence(req.query, r)
        items.append({'file':r.get('file',''),'code':code,'heading':r.get('heading','')[:80],
            'rank':idx,'score':score,'confidence':confidence,'confidence_meta':confidence_meta,
            'route':route,'text':(r.get('text','') or '')[:1200],'source':r.get('_source','search'),
            'pos':r.get('pos',0)})
    return {'query':req.query,'results':items,'total':len(items),'took_ms':elapsed}

@app.get("/api/suggest")
def api_suggest(q: str=Query(...)):
    if not _suggest_cache:
        return JSONResponse({'suggestions': []})
    ql = q.lower().strip()
    if len(ql) < 1:
        return JSONResponse({'suggestions': []})
    tokens = ql.split()
    # 编码规范化: GB50204 → gb 50204, 用于前缀匹配
    ql_norm = re.sub(r'[-_\s/]', '', ql)
    scored = []
    for item in _suggest_cache:
        tl = item['text'].lower()
        tl_norm = re.sub(r'[-_\s/]', '', tl)
        # 前缀匹配得分最高 (包含规范化编码匹配)
        if tl.startswith(ql) or tl_norm.startswith(ql_norm):
            scored.append((0, item['text'], item))
        elif all(t in tl for t in tokens):
            scored.append((1, item['text'], item))
        elif ql in tl:
            scored.append((2, item['text'], item))
    scored.sort(key=lambda x: (x[0], len(x[1])))
    seen_texts = set()
    result = []
    for _, _, item in scored:
        if item['text'] not in seen_texts:
            seen_texts.add(item['text'])
            result.append(item)
        if len(result) >= 8:
            break
    return {'suggestions': result, 'took_ms': 0}

@app.get("/api/changelog")
def api_changelog():
    entries = []
    for fname in os.listdir(KB_DIR):
        if not fname.endswith('.md'): continue
        fpath = os.path.join(KB_DIR, fname)
        try:
            st = os.stat(fpath)
            mtime = st.st_mtime
            ctime = st.st_ctime
            name = fname.replace('.md', '')
            for seg in ['_seg0_','_seg1_','_seg2_','_seg3_']:
                name = name.replace(seg, '')
            name = re.sub(r'_p\d{4}-\d{4}', '', name).strip()
            m = re.search(r'(GB|JGJ|CJJ|CECS|TCECS|DB\d*|JTG|JTJ|TB|DL|SL|SH|SY|HG|YB|JG|SB)[\sT/_]?(\d+(?:\.\d+)?(?:-\d+)?)', name)
            code = (m.group(1)+m.group(2)).replace(' ','').replace('_','/') if m else name[:30]
            rname = name.replace(code, '').strip() if code != name[:30] else name
            is_new = abs(mtime - ctime) < 60
            entries.append({'code': code, 'name': rname or name, 'file': fname,
                'mtime': mtime, 'is_new': is_new})
        except Exception:
            pass
    entries.sort(key=lambda x: x['mtime'], reverse=True)
    return {'entries': entries[:30], 'total': len(entries)}

@app.get("/api/clause")
def api_clause(code: str=Query(...), clause: str=Query(...), pos: int=Query(0)):
    ci = load_clause_index()
    if not ci: return JSONResponse({'error':'no index'},404)
    clean_code = code.replace(' ','').replace('-','').replace('_','/')
    # 如果有 pos，按位置精确匹配 (处理罗马数字同名歧义)
    if pos > 0:
        for fname, data in ci['index'].items():
            sc = data.get('std_code','')
            if sc and clean_code not in sc.replace(' ','').replace('-','').replace('_','/'):
                continue
            best = None
            for c in data['clauses']:
                if c['number'] != clause:
                    continue
                cp = c.get('pos', 0)
                if abs(cp - pos) < 100:
                    best = c
                    break
                if best is None or abs(cp - pos) < abs(best.get('pos', 0) - pos):
                    best = c
            if best:
                fpath = os.path.join(KB_DIR, fname)
                if os.path.exists(fpath):
                    with open(fpath,'r',encoding='utf-8',errors='replace') as f: text = f.read()
                    return {'code':data.get('std_code',''),'clause':best['number'], 'file':fname, 'pos':best.get('pos',0),
                            'heading':best['title'],'text':_extract_clause_text(text, best['pos'], best['length'], best['number'])}
    # Search lookup table
    for key, entry in ci.get('lookup',{}).items():
        key_code = key.split(':')[0]
        if clean_code in key_code.replace(' ','').replace('-','').replace('_','/') and clause in key:
            fpath = os.path.join(KB_DIR, entry['fname'])
            if os.path.exists(fpath):
                with open(fpath,'r',encoding='utf-8',errors='replace') as f: text = f.read()
                return {'code':key_code,'clause':entry['number'], 'file':entry['fname'], 'pos':entry.get('pos',0), 'heading':entry['title'],
                        'text':_extract_clause_text(text, entry['pos'], entry['length'], entry['number'])}
    # Fallback: scan clauses, but ONLY within the requested standard's files.
    # Without this code check, any standard's clause with the same number would
    # be returned as if it belonged to the requested code — a cross-standard
    # false citation (e.g. GB99999 §5.5.4 returning CECS164's §5.5.4).
    for fname, data in ci['index'].items():
        sc = data.get('std_code', '')
        if sc and clean_code not in sc.replace(' ', '').replace('-', '').replace('_', '/'):
            continue
        for c in data['clauses']:
            if c['number'] == clause:
                fpath = os.path.join(KB_DIR, fname)
                if os.path.exists(fpath):
                    with open(fpath,'r',encoding='utf-8',errors='replace') as f: text = f.read()
                    return {'code':data.get('std_code',fname[:40]),'clause':c['number'], 'file':fname, 'pos':c.get('pos',0), 'heading':c['title'],
                            'text':_extract_clause_text(text, c['pos'], c['length'], c['number'])}
    text = get_kb().read_clause(code, clause)
    return JSONResponse({'error':'not found'},404) if not text else {'code':code,'clause':clause,'text':text,'heading':''}

@app.get("/api/document")
def api_document(code: str=Query(...)):
    """返回完整 MD 文本 (含锚点) + 从 MD 标题解析的树, 前端全量渲染 + 锚点跳转"""
    ci = load_clause_index()
    if not ci: return JSONResponse({'error':'no index'},404)
    clean_code = code.replace(' ','').replace('-','').replace('_','/')

    matches = []
    for fname, data in ci['index'].items():
        sc = data.get('std_code','')
        name = re.sub(r'^_seg\d+_','',fname).replace('.md','')
        name = re.sub(r'_p\d{4}-\d{4}','',name)
        if sc and not sc.startswith('_seg'):
            if clean_code in sc.replace(' ','').replace('-','').replace('_','/'):
                matches.append(fname)
        elif code in name or name in code or code[:20] in fname:
            matches.append(fname)
    if not matches:
        return JSONResponse({'error':'not found'},404)

    # 读取并拼接 MD
    full_text = ''
    offset = 0
    for fname in matches:
        fpath = os.path.join(KB_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath,'r',encoding='utf-8',errors='replace') as f:
                seg_text = f.read()
                full_text += seg_text + '\n\n---\n\n'
                offset += len(seg_text) + len('\n\n---\n\n')

    # ── 正文起点定位 (同步 kb_resolver_core._find_body_start) ──
    _body_start = 0
    _toc_pos = re.search(r'^#{1,3}\s+(?:目\s*次|目\s*录)\s*$', full_text, re.MULTILINE)
    _scan_from = _toc_pos.end() if _toc_pos else 0
    for _pat in [r'^#{1,3}\s+\d+\s+总\s*则', r'^#{1,3}\s+基本规定',
                 r'^#{1,3}\s+总\s*则', r'^#{1,3}\s+\d+\s+一般规定']:
        _bm = re.search(_pat, full_text[_scan_from:], re.MULTILINE)
        if _bm:
            _body_start = _scan_from + _bm.start()
            break
    if _body_start == 0 and _scan_from > 0:
        # 回退: 目次后第一个非页码标题
        for _m in re.finditer(r'^(#{1,3})\s+(.+)$', full_text[_scan_from:], re.MULTILINE):
            _h = _m.group(2).strip()
            if not re.search(r'(?:……\s*\d{1,4}|\s{2,}\d{1,4})\s*$', _h) and len(_h) > 3:
                _body_start = _scan_from + _m.start()
                break

    # ── 从 MD 文本直接解析标题 → 按编号层级建树 ──
    _h_pat = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)
    _num_pat = re.compile(r'^(?:第[一二三四五六七八九十百千\d]+[章节])|(?:\d+(?:\.\d+)*)|(?:[IVXLCDM\u2160-\u217B]+)|(?:[（(][一二三四五六七八九十]+[）)])|(?:[一二三四五六七八九十]+[、．.])')
    _is_roman = re.compile(r'^[IVXLCDM\u2160-\u217B]+$')
    raw = []
    for m in _h_pat.finditer(full_text):
        h = m.group(2).strip()
        num_m = _num_pat.match(h)
        number = num_m.group(0).rstrip('.。、 ') if num_m else ''
        title = h[len(number):].strip() if number else h
        raw.append({'number': number, 'title': title, 'pos': m.start(), 'full': h})

    # 过滤: 正文起点之前全部跳过 + 噪音 + TOC
    _front_kw = {'前言','目次','目录','Contents','修订说明','编制说明','条文说明','公告','通知','中华人民共和国',
                 '本规范用词说明','引用标准名录','本标准用词说明'}
    _toc_pat = re.compile(r'(?:……|…)\s*[（(]?\d{1,4}[）)]?\s*$')
    _toc_pg_pat = re.compile(r'\s{2,}\d{1,4}\s*$')
    raw2 = []
    for h in raw:
        f = h['full']
        # 正文起点之前: 全部跳过
        if _body_start > 0 and h['pos'] < _body_start:
            continue
        if any(kw in f for kw in _front_kw): continue
        if _toc_pat.search(f) or _toc_pg_pat.search(f): continue
        # 条款正文: 纯数字编号但文本 > 35 字 → 跳过
        if h['number'] and re.match(r'^\d+$', h['number']) and len(f) > 35: continue
        raw2.append(h)
    raw = raw2

    # 去重: 同名编号保留较短文本 (标题 < TOC条目 < 条款正文)
    seen = {}
    dedup = []
    for h in raw2:
        n = h['number']
        if n and n in seen:
            idx = seen[n]
            old_len = len(dedup[idx]['full'])
            new_len = len(h['full'])
            # 更短的文本更可能是真正的标题
            if new_len < old_len:
                dedup[idx] = h
        else:
            if n: seen[n] = len(dedup)
            dedup.append(None)
            dedup[-1] = h
    raw = [h for h in dedup if h is not None]

    # 按 pos 排序
    raw.sort(key=lambda x: x['pos'])

    # 编号层级建树: "3.2.1" → parent="3.2", "I" → 继承上一个阿拉伯编号
    last_arabic = None
    tree_nodes = []  # [(number, title, pos, parent_number, depth)]
    for h in raw:
        n = h['number']
        if not n:
            # 无编号标题: 放在上一个编号标题下
            tree_nodes.append((h['full'][:20], h['title'], h['pos'], last_arabic, 1 if last_arabic else 0))
            continue
        if _is_roman.match(n):
            parent = last_arabic
            tree_nodes.append((n, h['title'], h['pos'], parent, 1 if parent else 0))
            continue
        # 阿拉伯编号: 用点号推断父级
        parts = n.split('.')
        if len(parts) > 1:
            parent = '.'.join(parts[:-1])
            depth = len(parts) - 1
        else:
            parent = None
            depth = 0
        last_arabic = n
        tree_nodes.append((n, h['title'], h['pos'], parent, depth))

    # 展平为前端树
    # 建立 number → first_index 映射
    num_to_idx = {}
    for i, (n, _, _, _, _) in enumerate(tree_nodes):
        if n and n not in num_to_idx:
            num_to_idx[n] = i

    # 为每个节点计算最终深度 (追踪父链)
    def get_depth(idx):
        _, _, _, parent, base_depth = tree_nodes[idx]
        if parent and parent in num_to_idx:
            parent_idx = num_to_idx[parent]
            if parent_idx < idx:  # 父在子前
                return get_depth(parent_idx) + 1
        return base_depth

    tree_items = []
    for i, (n, title, pos, parent, _) in enumerate(tree_nodes):
        tree_items.append({
            'number': n, 'title': title, 'pos': pos,
            'depth': get_depth(i)
        })

    # ── 在标题行末尾插入锚点 (倒序), marked渲染后锚点在h1~h4内部,scrollIntoView直滚标题元素 ──
    for i in range(len(tree_items)-1, -1, -1):
        p = tree_items[i]['pos']
        if p > 0 and p < len(full_text):
            end = full_text.find('\n', p)
            if end < 0: end = len(full_text)
            anchor = f'<a id="tx{i}" style="scroll-margin-top:20px"></a>'
            full_text = full_text[:end] + anchor + full_text[end:]

    return {'code': code, 'text': full_text, 'tree': tree_items, 'segments': len(matches)}

@app.get("/api/status")
def api_status(): return get_kb().status()

@app.get("/api/standards")
def api_standards():
    ci = load_clause_index()
    if not ci: return JSONResponse({'error':'no index'},404)

    # Merge _seg segments by cleaned source name
    merged = {}
    for fname, data in ci['index'].items():
        # Clean filename to get source name
        name = re.sub(r'^_seg\d+_','',fname).replace('.md','')
        name = re.sub(r'_p\d{4}-\d{4}','',name)
        code = data.get('std_code','')
        # Use code as merge key, or cleaned name for NO_CODE
        if code and not code.startswith('_seg'):
            key = code
        else:
            key = name  # merge by cleaned name
        if key not in merged:
            merged[key] = {'code':code,'name':name,'count':0,'segments':0}
        merged[key]['count'] += len(data['clauses'])
        merged[key]['segments'] += 1

    # Group by prefix
    groups = {}
    order = ['GB','JGJ','CJJ','CECS','TCECS','DB','JC','RISN','JTG','MANUAL','REFBOOK','GUIDE','OTHER']
    labels = {'GB':'国标 GB','JGJ':'行标 JGJ','CJJ':'城镇 CJJ','CECS':'协会 CECS','TCECS':'协会 TCECS',
              'DB':'地方 DB','JC':'建材 JC','RISN':'行业 RISN','JTG':'公路 JTG',
              'MANUAL':'施工手册','REFBOOK':'设计参考书','GUIDE':'指南/导则','OTHER':'其他'}
    for key, m in merged.items():
        code = m['code']; name = m['name']
        if not code or code.startswith('_seg'):
            if '\u65bd\u5de5\u624b\u518c' in name: pfx = 'MANUAL'
            elif '\u8bbe\u8ba1\u5e38\u89c1\u95ee\u9898' in name: pfx = 'REFBOOK'
            elif '\u6307\u5357' in name or '\u6307\u5bfc' in name: pfx = 'GUIDE'
            else: pfx = 'OTHER'
            code = name[:40]
        else:
            m2 = re.match(r'([A-Z]+)', code)
            pfx = m2.group(1) if m2 else 'OTHER'
        if pfx not in order: pfx = 'OTHER'
        if pfx not in groups: groups[pfx] = []
        groups[pfx].append({'code':code,'name':name,'count':m['count'],'segments':m['segments']})
    result = []
    for pfx in order:
        if pfx in groups:
            result.append({'prefix':pfx,'label':labels.get(pfx,pfx),'items':sorted(groups[pfx],key=lambda x:x['code'])})
    return {'groups':result,'total':sum(len(g['items']) for g in result)}

@app.get("/api/tree")
def api_tree(code: str=Query(...)):
    ci = load_clause_index()
    if not ci: return JSONResponse({'error':'no index'},404)
    clean_code = code.replace(' ','').replace('-','').replace('_','/')

    matches = []
    for fname, data in ci['index'].items():
        sc = data.get('std_code','')
        name = re.sub(r'^_seg\d+_','',fname).replace('.md','')
        name = re.sub(r'_p\d{4}-\d{4}','',name)
        # Match by code or by cleaned name
        if sc and not sc.startswith('_seg'):
            if clean_code in sc.replace(' ','').replace('-','').replace('_','/'):
                matches.append(fname)
        elif code in name or name in code or code[:20] in fname:
            matches.append(fname)
    if not matches: return JSONResponse({'error':'not found'},404)

    # Merge clauses from all matching segments
    _is_roman = re.compile(r'^[IVXLCDM\u2160-\u217B]+$')
    tree = {}
    roman_clauses = []

    for fname in matches:
        for c in ci['index'][fname]['clauses']:
            parts = c['number'].split('.')
            # Roman numeral clauses need parent-based placement (second pass)
            if len(parts) == 1 and _is_roman.match(parts[0]):
                roman_clauses.append(c)
                continue

            node = tree
            for i, p in enumerate(parts):
                key = '.'.join(parts[:i+1])
                if key not in node:
                    node[key] = {'number':key,'title':'','children':{},'pos':0}
                if i == len(parts)-1 and c['title']:
                    node[key]['title'] = c['title']
                    node[key]['pos'] = c.get('pos', 0)
                node = node[key]['children']

    # Second pass: attach Roman numeral clauses under their parent
    def _find_node(node_dict, key):
        if key in node_dict:
            return node_dict
        for v in node_dict.values():
            found = _find_node(v.get('children', {}), key)
            if found:
                return found
        return None

    for c in roman_clauses:
        parent_key = c.get('parent')
        parent_node = _find_node(tree, parent_key) if parent_key else None
        if parent_node and parent_key:
            children = parent_node[parent_key].setdefault('children', {})
            rk = c['number']
            cpos = c.get('pos', 0)
            if rk not in children:
                children[rk] = {'number': rk, 'title': c['title'], 'children': {}, 'pos': cpos}
            else:
                existing_pos = children[rk].get('pos', 0)
                # pos 间距 > 50000 → 条文说明重复, 跳过
                if abs(cpos - existing_pos) < 50000:
                    alt_key = f"{parent_key}>{rk}"
                    children[alt_key] = {'number': alt_key, 'title': c['title'], 'children': {}, 'pos': cpos}
        else:
            if c['number'] not in tree:
                tree[c['number']] = {'number': c['number'], 'title': c['title'], 'children': {}, 'pos': c.get('pos', 0)}
    roman_map = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,
                 'X':10,'XI':11,'XII':12,'XIII':13,'XIV':14,'XV':15,'XVI':16,'XVII':17,'XVIII':18,'XIX':19,'XX':20,
                 'Ⅰ':1,'Ⅱ':2,'Ⅲ':3,'Ⅳ':4,'Ⅴ':5,'Ⅵ':6,'Ⅶ':7,'Ⅷ':8,'Ⅸ':9,'Ⅹ':10,'Ⅺ':11,'Ⅻ':12,
                 'ⅰ':1,'ⅱ':2,'ⅲ':3,'ⅳ':4,'ⅴ':5,'ⅵ':6,'ⅶ':7,'ⅷ':8,'ⅸ':9,'ⅹ':10,'ⅺ':11,'ⅻ':12}
    def _sort_key(x):
        parts = []
        for p in x.split('.'):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(roman_map.get(p, 9999))
        return parts
    def flatten(d, depth=0):
        items = []
        for k in sorted(d.keys(), key=_sort_key):
            v = d[k]
            items.append({'number':v['number'],'title':v['title'],'depth':depth,'pos':v.get('pos',0)})
            items.extend(flatten(v['children'], depth+1))
        return items
    first_code = ci['index'][matches[0]].get('std_code','')
    return {'code':first_code or re.sub(r'^_seg\d+_','',matches[0])[:40],'tree':flatten(tree),'segments':len(matches)}

@app.get("/api/params")
def api_params(name: str=Query(None)):
    # param_index retired: there is no curated value table. Without a name there
    # is nothing to browse; with a name we route to clause search so the answer
    # is the governing clause text (with its conditions), not a bare, conflated,
    # context-stripped value.
    if not name:
        return {'params': [], 'note': 'param_index 已退役：请直接检索术语以获取相关条文'}
    kb = get_kb()
    results = kb.search(name, max_results=15)
    entries = []
    for r in results:
        m = re.search(r'(GB|JGJ|CJJ|CECS|TCECS|DB\d*|CJ|JTG|JTJ|TB|DL|SL|SH|SY|HG|YB|JG|SB)[\sT/_]?(\d+(?:\.\d+)?(?:-\d+)?)', r.get('file',''))
        code = (m.group(1)+m.group(2)).replace(' ','').replace('_','/') if m else r.get('standard_code','')
        heading = (r.get('heading','') or '')
        entries.append({
            'std_code': code,
            'clause': heading.split()[0] if heading else '',
            'value': heading[:60],
            'text': (r.get('text','') or '')[:600],
            'source': 'clause_search',
        })
    return {'name': name, 'entries': entries, 'total': len(entries), 'mode': 'clause_search'}

# ===== Web UI =====

# Old web UI removed — frontend is now Obsidian-only
@app.get("/", response_class=JSONResponse)
def index():
    return {"service": "知微 KB v3", "status": "running", "frontend": "Obsidian plugin at data/index/.obsidian/plugins/zhiwei-kb-search/"}
IMAGES_DIR = os.path.join(_ROOT_DIR, 'data', 'images')
if os.path.isdir(IMAGES_DIR):
    app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")




# Load reference index
_ref_index = None
_ref_norm_index = None

def _normalize_ref_code(code: str) -> str:
    # 委托 code_norm.normalize_code 单一真源 (v1 退役后 v2 接管, 含 RISN/T-CECS/DB)。
    # 旧自写 replace/regex 对 RISN 会把年份粘进码 (RISN-TG026-2020→RISN-TG0262020), 已弃。
    from kb_core.code_norm import normalize_code
    return normalize_code(code or "")

def _load_ref_index():
    global _ref_index, _ref_norm_index
    if _ref_index is None:
        p = os.path.join(_KB_JSON_DIR, "kb_cross_refs.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                _ref_index = json.load(f)
        else:
            _ref_index = {"target_to_source": {}, "refs": []}
    if _ref_norm_index is None:
        target_to_source = _ref_index.get("target_to_source", {}) if isinstance(_ref_index, dict) else {}
        _ref_norm_index = {}
        for target, sources in target_to_source.items():
            key = _normalize_ref_code(target)
            if not key:
                continue
            bucket = _ref_norm_index.setdefault(key, set())
            for source in sources:
                bucket.add(_normalize_ref_code(source) or source.upper())
    return _ref_index

@app.get("/api/refs")
def api_refs(code: str = ""):
    idx = _load_ref_index()
    if not code:
        return {"total_codes": len(idx.get("target_to_source", {})), "total_refs": len(idx.get("refs", []))}
    key = _normalize_ref_code(code)
    target_to_source = idx.get("target_to_source", {}) if isinstance(idx, dict) else {}
    by = sorted(_ref_norm_index.get(key, set()))
    refs_to = []
    for target, sources in target_to_source.items():
        if key in {_normalize_ref_code(source) for source in sources}:
            refs_to.append(target)
    refs_to = sorted({_normalize_ref_code(item) or item for item in refs_to})
    return {
        "code": key or code.upper(),
        "refs_by_count": len(by),
        "refs_to_count": len(refs_to),
        "refs_by": [{"code": item, "ctx": ""} for item in by[:10]],
        "refs_to": [{"code": item, "ctx": ""} for item in refs_to[:10]],
    }


if __name__ == '__main__':
    print("知微 KB v3 启动: http://localhost:8765")
    _build_suggest_index()
    print(f"  自动补全索引: {len(_suggest_cache)} 条候选词")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
