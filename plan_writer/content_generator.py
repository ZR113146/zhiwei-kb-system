#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
content_generator v2.0 — 通用从零编制引擎。
读取project_brief → 识别项目类型 → 匹配KB规范 → 生成content/*.md。
跨专业可用：园林景观/市政道路/混凝土结构/钢结构/电气/给排水等。
"""

import os, re, sys, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kb_core'))
from kb import KB
import changelog; changelog.record(__file__, sys.argv)

# === 加载规范标签和项目类型映射 ===
REF_DIR = os.path.dirname(__file__)

def _load_json(filename):
    path = os.path.join(REF_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

STANDARD_TAGS = _load_json('standard_tags.json')
PROJECT_TYPE_MAP = _load_json('project_type_map.json')

# === 通用章节框架（施工手册第1分册 §2.5.4.3） ===
SECTION_DEPTH = {
    'ch01': {
        'standards': 12,   # 最少引用规范数
        'laws': 5,         # 最少法律法规
    },
    'ch02': {
        'info_table': True,
        'machinery_table': True,
        'scope_detail': True,
        'key_points': True,
    },
    'ch03': {
        'org_chart': True,
        'labor_plan': True,     # 劳动力计划表
        'schedule_table': True,
        'flow_chart': True,
    },
    'ch04': {
        'test_plan': True,
        'sample_plan': True,
        'material_list': True,  # 材料清单含数量
    },
    'ch05': {
        'min_subsections': 6,   # 最少分项工程数
        'clause_per_section': 2, # 每分项最少2条规范引用
        'table_per_section': 1,  # 每分项至少1个允许偏差表
    },
    'ch06': {
        'qc_points_table': True,
        'acceptance_division': True,
        'defect_prevention': True,
    },
    'ch07': {
        'safety_per_process': True,
        'emergency_plan': True,
    },
    'ch08': {
        'dust_noise_waste': True,
        'seasonal': True,
    },
    'ch09': {
        'schedule_measures': True,
        'product_protection': True,
        'cost_reduction': True,
    },
}


class ContentGenerator:
    def __init__(self, project_brief_path, content_dir):
        self.kb = KB()
        self.content_dir = content_dir
        os.makedirs(self.content_dir, exist_ok=True)
        self.brief = self._load_brief(project_brief_path)
        self.project_types = self._identify_project_types()
        self.matched_standards = self._match_standards()

    def _load_brief(self, path):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ''

    def _b(self, field):
        m = re.search(rf'{re.escape(field)}[：:]\s*(.+?)(?:\n|$)', self.brief)
        return m.group(1).strip() if m else ''

    def _identify_project_types(self):
        """从brief识别项目类型。用关键词长度评分，过滤短词误匹配。
        例：'防火涂料'不再误匹配建筑装饰('涂料'2字)。"""
        scores = {}
        for ptype, info in PROJECT_TYPE_MAP.get('mappings', {}).items():
            best_len = 0
            for kw in info.get('keywords', []):
                if kw in self.brief and len(kw) > best_len:
                    best_len = len(kw)
            if best_len > 0:
                scores[ptype] = best_len

        if not scores:
            print(f'  WARNING: No project type matched from brief — defaulting to 园林景观')
            return ['\u56ed\u6797\u666f\u89c2']  # 兜底

        # 只保留最高分词长的类型（允许并列），过滤掉短词误匹配
        max_score = max(scores.values())
        types = [t for t, s in scores.items() if s >= max_score]
        # 但若只有1个类型且分低，也保留（确实是这个领域）
        if len(types) == 1:
            return types
        # 多类型并列时只保留前3个（防止匹配泛滥）
        return types[:3]

    def _match_standards(self):
        """按项目类型匹配KB中的规范 → {category: [standard_codes]}"""
        needed_categories = set()
        for pt in self.project_types:
            info = PROJECT_TYPE_MAP['mappings'].get(pt, {})
            needed_categories.update(info.get('categories', []))
            needed_categories.update(info.get('optional', []))

        matched = {}
        for code, cats in STANDARD_TAGS.get('standards', {}).items():
            for cat in cats:
                if cat in needed_categories:
                    matched.setdefault(cat, []).append(code)
                    break
        return matched

    def _get_standards_for_ch01(self):
        """获取编制依据规范列表。
        过滤规则：跨领域标签(质量验收/施工安全/环境噪声)不单独决定包含——
        标准必须至少有一个非跨领域标签与项目类型匹配。"""
        # 跨领域标签——不能单独作为匹配依据
        CROSSCUT = {'质量验收', '施工安全', '环境噪声', '设计通用', '材料标准', '地方标准'}
        # 项目专属类别（排除了跨领域标签）
        project_cats = set()
        for pt in self.project_types:
            info = PROJECT_TYPE_MAP['mappings'].get(pt, {})
            for cat in info.get('categories', []):
                if cat not in CROSSCUT:
                    project_cats.add(cat)
            for cat in info.get('optional', []):
                if cat not in CROSSCUT:
                    project_cats.add(cat)

        # 归类：优先 → 专业 → 其余
        priority = ['质量验收', '施工安全', '环境噪声']
        seen = set()
        result = []

        for cat in priority:
            for code in self.matched_standards.get(cat, []):
                if code in seen:
                    continue
                code_cats = set(STANDARD_TAGS.get('standards', {}).get(code, []))
                specific_cats = code_cats - CROSSCUT
                # 专业标准：有专属标签且匹配项目 → 纳入
                # 或：无专属标签（纯跨领域标准如 GB50300）→ 一律纳入
                if not specific_cats or (specific_cats & project_cats):
                    result.append(code)
                    seen.add(code)

        for cat, codes in sorted(self.matched_standards.items()):
            if cat in priority:
                continue
            for code in codes:
                if code in seen:
                    continue
                code_cats = set(STANDARD_TAGS.get('standards', {}).get(code, []))
                specific_cats = code_cats - CROSSCUT
                if not specific_cats or (specific_cats & project_cats):
                    result.append(code)
                    seen.add(code)

        if len(result) > 18:
            print(f'  NOTE: {len(result)} standards matched, using top 18 (limit configurable)')
        return result[:18]

    def _clause(self, code, clause):
        t = self.kb.read_clause(code, clause)
        return t if t and len(t) > 20 else ''

    def _kb_clause_text(self, code, clause):
        """Get full clause text from KB, return empty string if not found"""
        t = self.kb.read_clause(code, clause)
        return t if t and len(t) > 20 else ''

    # ================================================================
    #  Chapter generators — each returns markdown string
    # ================================================================

    def generate_ch01(self):
        """编制依据 — 从KB动态匹配规范列表"""
        codes = self._get_standards_for_ch01()
        md = '''# 1  编制依据

## 1.1  合同文件
- 本工程施工招标文件及施工合同。
- 建设单位对本工程的施工要求、设计交底及相关会议纪要。

## 1.2  设计文件
- 本工程全套施工图纸。
- 施工单位编制的项目总体施工组织设计。
- 监理单位编制的监理规划及监理实施细则。
- 本工程工程量清单及招标控制价。
- 本工程场地地质勘察报告。

## 1.3  法律法规
- 《中华人民共和国建筑法》（2019年修正）
- 《中华人民共和国安全生产法》（2021年修正）
- 《中华人民共和国环境保护法》（2014年修订）
- 《建设工程安全生产管理条例》（国务院令第393号）
- 《建设工程质量管理条例》（国务院令第279号）

## 1.4  国家及行业规范标准

| 序号 | 标准编号 | 标准名称 |
|---|---|---|
'''
        for i, code in enumerate(codes, 1):
            name, layer, confidence = self.kb.get_name(code)
            if not name:
                name = code
            md += f'| {i} | {code} | {name} |\n'

        md += '''
## 1.5  地方规范标准
- 《南京市城市绿化施工技术规范》（DB3201/T 1012-2021）
- 《南京市市政工程施工质量验收规范》（DB3201/T 1001-2019）
- 《南京市建设工程施工现场扬尘污染防治管理办法》（宁政办发〔2023〕45号）
- 《南京市绿化养护管理规范》（DB3201/T 1013-2021）
- 《江苏省建筑施工安全文明工地标准》（DGJ32/J 16-2019）
- 《江苏省园林绿化工程施工质量验收规范》（DGJ32/J 121-2018）

## 1.6  企业内部文件
- 企业施工技术管理制度。
- 《建筑施工手册》（第六版）第1~6分册。
- 危险性较大分部分项工程专项方案管理制度。
'''
        return md


    # === Ch02~Ch09: skeleton template system ===
    # Content expansion handled by AI via Phase1+Phase2 from content/*.md templates.


    def _chapter_skeleton(self, chapter_no, title, sections):
        md = [f'# {chapter_no}  {title}', '']
        for idx, (section_title, body) in enumerate(sections, 1):
            md.append(f'## {chapter_no}.{idx}  {section_title}')
            md.append(body)
            md.append('')
        return '\n'.join(md)

    def generate_skeleton_chapters(self):
        title = self._b('项目名称') or '本工程'
        location = self._b('地点') or '项目所在地'
        scope = self._b('工程范围') or '按设计图纸及合同约定范围施工'
        return {
            'ch02.md': self._chapter_skeleton('2', '工程概况', [
                ('工程基本信息', f'本工程为{title}，建设地点位于{location}，施工范围为{scope}。'),
                ('施工范围', '施工内容包括场地准备、土方与基础、主体施工、配套安装、质量验收和移交。'),
                ('重难点分析', '重点控制测量放线、材料进场验收、交叉作业协调、成品保护和雨季施工组织。'),
            ]),
            'ch03.md': self._chapter_skeleton('3', '施工安排', [
                ('总体部署', '按先准备、后主体、再配套、最终验收的顺序组织流水施工。'),
                ('组织机构', '项目经理负责总体协调，技术负责人负责技术质量，安全质量负责人负责现场安全与验收。'),
                ('进度安排', '按施工准备、专业施工、质量验收、整改移交四个阶段控制节点。'),
            ]),
            'ch04.md': self._chapter_skeleton('4', '施工准备', [
                ('技术准备', '施工前完成图纸会审、技术交底、专项方案审批和测量控制点复核。'),
                ('材料机具准备', '材料进场应具备质量证明文件，并按规范要求进行复检。'),
                ('现场准备', '完成临水临电、围挡、道路、材料堆场和安全文明施工设施布置。'),
            ]),
            'ch05.md': self._chapter_skeleton('5', '主要施工方法', [
                ('施工流程', '施工流程为测量放线、基层处理、分项施工、过程检查、成品保护和验收移交。'),
                ('土方与基础', '土方开挖和回填应分层施工，压实质量按设计和相关验收规范控制。'),
                ('铺装与配套', '铺装面层应控制标高、平整度、坡向和接缝质量，配套安装应满足功能和安全要求。'),
                ('绿化与养护', '苗木进场、种植、支撑、浇水和养护应按园林绿化相关规范执行。'),
            ]),
            'ch06.md': self._chapter_skeleton('6', '质量要求', [
                ('质量目标', '工程质量目标为合格，检验批、分项、分部工程验收应符合现行规范。'),
                ('质量控制', '实行材料验收、样板引路、过程检查、隐蔽验收和整改闭环管理。'),
                ('通病防治', '重点防治空鼓、开裂、沉陷、积水、污染和成品破坏。'),
            ]),
            'ch07.md': self._chapter_skeleton('7', '安全管理', [
                ('安全目标', '安全管理坚持预防为主，落实班前教育、风险告知和现场巡查。'),
                ('工序安全', '机械作业、临时用电、高处作业和交叉作业应设置专项防护措施。'),
                ('应急管理', '建立应急组织、通讯联系、物资储备和事故报告流程。'),
            ]),
            'ch08.md': self._chapter_skeleton('8', '文明施工与环境保护', [
                ('文明施工', '现场实行围挡封闭、材料定置堆放、道路清扫和垃圾及时清运。'),
                ('扬尘噪声控制', '采取湿法作业、覆盖、浇水、车辆冲洗和低噪声设备等措施。'),
                ('季节性措施', '雨季重点控制排水、防滑、防雷和材料防潮。'),
            ]),
            'ch09.md': self._chapter_skeleton('9', '其他要求', [
                ('工期保证', '通过计划分解、资源协调、工序穿插和每日复盘保证节点。'),
                ('成品保护', '对已完成工程采取覆盖、隔离、警示和移交验收措施。'),
                ('资料管理', '施工记录、检验批、材料证明和验收资料应同步收集归档。'),
            ]),
        }
    def _write_standards_guide(self):
        """为 AI 扩展 ch02~ch09 生成规范引用指南。"""
        from kb_auditor import CHAPTER_MAP
        from retrieval_core import RetrievalCore

        retrieval = RetrievalCore(self.kb)
        guide = {}
        for ch_key in sorted(CHAPTER_MAP.keys()):
            topics = CHAPTER_MAP[ch_key].get('topic_standards', {})
            if not topics:
                continue
            ch_guide = {}
            for topic, codes in topics.items():
                response = retrieval.match({
                    'mode': 'chapter_recommend',
                    'constraints': {'chapter': ch_key, 'topic': topic, 'codes': codes},
                    'limits': {'max_clauses': 3},
                })
                ch_guide[topic] = [
                    {
                        'code': item['code'],
                        'name': item['name'],
                        'top_clauses': [c['heading'] for c in item.get('clauses', [])],
                        'citations': item.get('citations', []),
                    }
                    for item in response['results']
                ]
            guide[ch_key] = {
                'name': CHAPTER_MAP[ch_key]['name'],
                'topics': ch_guide,
            }
        self._write('standards_guide.json', json.dumps(guide, ensure_ascii=False, indent=2))

    def _write_project_json(self):
        """Write project.json with detected types and matched categories.
        AI reads this to know which standards and project type to use."""
        title = self._b('\u9879\u76ee\u540d\u79f0') or '\u3010\u9879\u76ee\u540d\u79f0\u3011'
        location = self._b('\u5730\u70b9') or '\u3010\u5730\u70b9\u3011'
        builder = self._b('\u5efa\u8bbe\u5355\u4f4d') or '\u3010\u5efa\u8bbe\u5355\u4f4d\u3011'

        cfg = {
            '_description': '\u9879\u76ee\u914d\u7f6e\u6587\u4ef6\u3002\u7531 content_generator \u81ea\u52a8\u586b\u5145\u3002',
            '_ai_guide': '\u6269\u5c55ch02~ch09\u65f6\uff0c\u8bfb\u53d6standards_guide.json\u83b7\u53d6\u6bcf\u7ae0\u4e13\u9898\u5e94\u5f15\u7528\u7684\u89c4\u8303\u6761\u6b3e\u3002',
            '_version': '1.0',
            'title': title,
            'subtitle': '\u4e13\u9879\u65bd\u5de5\u65b9\u6848',
            'company': builder,
            'date': '\u3010\u65e5\u671f\u3011',
            'reviewer': None,
            'project_types': self.project_types,
            'matched_categories': list(self.matched_standards.keys()),
            'matched_standards': self.matched_standards,
            'section_depth': SECTION_DEPTH,
        }
        self._write('project.json', json.dumps(cfg, ensure_ascii=False, indent=2))

    def generate_all(self):
        """Generate: ch01(standards list) + project.json + Mermaid + preserve ch02~09 skeletons.
        AI handles ch02~ch09 content expansion from the skeleton templates."""
        self._write_project_json()
        self._write('ch01.md', self.generate_ch01())
        for filename, content in self.generate_skeleton_chapters().items():
            self._write(filename, content)
        self._gen_mermaid()
        self._write_standards_guide()
        n_standards = sum(len(v) for v in self.matched_standards.values())
        print(f'Generated: ch01~ch09.md + project.json + 4 Mermaid flowcharts + standards_guide.json')
        print(f'  Project types: {self.project_types}')
        print(f'  Matched standards: {n_standards}')
        print(f'  AI: expand content/ch02~ch09.md via Phase1+Phase2 workflow')

    def _gen_mermaid(self):
        """Auto-generate Mermaid flowcharts based on project type (4 charts)."""
        ptypes = self.project_types
        selected_flowchart = 'default_园林'

        # 1. Flowchart: main construction flow
        if any(t in ptypes for t in ['市政道路', '城市道路']):
            selected_flowchart = '道路'
            mmd = ('graph TD\n'
                   '    A[施工准备]:::start --> B[铣刨+拆除]:::process\n'
                   '    B --> C[基层+排水沟]:::process\n'
                   '    C --> D[沥青摊铺]:::key\n'
                   '    D --> E[人行道+附属]:::process\n'
                   '    E --> F[标线+验收]:::finish\n'
                   '    classDef start fill:#2563eb,color:#fff\n'
                   '    classDef process fill:#f59e0b,color:#000\n'
                   '    classDef key fill:#dc2626,color:#fff\n'
                   '    classDef finish fill:#16a34a,color:#fff\n')
        elif any(t in ptypes for t in ['钢结构']):
            selected_flowchart = '钢结构'
            mmd = ('graph TD\n'
                   '    A[施工准备]:::start --> B[基础验收]:::process\n'
                   '    B --> C[钢构件进场检验]:::process\n'
                   '    C --> D[钢柱/钢梁吊装]:::key\n'
                   '    D --> E[节点连接/焊接]:::key\n'
                   '    E --> F[防火/防腐涂装]:::process\n'
                   '    F --> G[验收]:::finish\n'
                   '    classDef start fill:#2563eb,color:#fff\n'
                   '    classDef process fill:#f59e0b,color:#000\n'
                   '    classDef key fill:#dc2626,color:#fff\n'
                   '    classDef finish fill:#16a34a,color:#fff\n')
        elif any(t in ptypes for t in ['给排水']):
            selected_flowchart = '给排水'
            mmd = ('graph TD\n'
                   '    A[施工准备]:::start --> B[沟槽开挖]:::process\n'
                   '    B --> C[垫层+基础]:::process\n'
                   '    C --> D[管道安装]:::key\n'
                   '    D --> E[检查井砌筑]:::process\n'
                   '    E --> F[闭水/闭气试验]:::key\n'
                   '    F --> G[回填+验收]:::finish\n'
                   '    classDef start fill:#2563eb,color:#fff\n'
                   '    classDef process fill:#f59e0b,color:#000\n'
                   '    classDef key fill:#dc2626,color:#fff\n'
                   '    classDef finish fill:#16a34a,color:#fff\n')
        elif any(t in ptypes for t in ['混凝土结构']):
            selected_flowchart = '混凝土结构'
            mmd = ('graph TD\n'
                   '    A[施工准备]:::start --> B[测量放线]:::process\n'
                   '    B --> C[钢筋制作安装]:::key\n'
                   '    C --> D[模板支设]:::process\n'
                   '    D --> E[混凝土浇筑]:::key\n'
                   '    E --> F[养护+拆模]:::process\n'
                   '    F --> G[验收]:::finish\n'
                   '    classDef start fill:#2563eb,color:#fff\n'
                   '    classDef process fill:#f59e0b,color:#000\n'
                   '    classDef key fill:#dc2626,color:#fff\n'
                   '    classDef finish fill:#16a34a,color:#fff\n')
        elif any(t in ptypes for t in ['砌体结构']):
            selected_flowchart = '砌体结构'
            mmd = ('graph TD\n'
                   '    A[施工准备]:::start --> B[基层清理]:::process\n'
                   '    B --> C[放线+皮数杆]:::process\n'
                   '    C --> D[砌筑施工]:::key\n'
                   '    D --> E[构造柱/圈梁]:::process\n'
                   '    E --> F[抹灰+养护]:::process\n'
                   '    F --> G[验收]:::finish\n'
                   '    classDef start fill:#2563eb,color:#fff\n'
                   '    classDef process fill:#f59e0b,color:#000\n'
                   '    classDef key fill:#dc2626,color:#fff\n'
                   '    classDef finish fill:#16a34a,color:#fff\n')
        else:  # default: 园林景观 / 建筑装饰
            mmd = ('graph TD\n'
                   '    A[施工准备]:::start --> B[拆除+清理]:::process\n'
                   '    B --> C[土方+基础]:::process\n'
                   '    C --> D[主体工程]:::key\n'
                   '    D --> E[安装+配套]:::process\n'
                   '    E --> F[面层/饰面]:::process\n'
                   '    F --> G[验收]:::finish\n'
                   '    classDef start fill:#2563eb,color:#fff\n'
                   '    classDef process fill:#f59e0b,color:#000\n'
                   '    classDef key fill:#dc2626,color:#fff\n'
                   '    classDef finish fill:#16a34a,color:#fff\n')
        self._write('\u65bd\u5de5\u603b\u4f53\u6d41\u7a0b\u56fe.mmd', mmd)

        # 2. Org chart (universal)
        self._write('\u7ec4\u7ec7\u673a\u6784\u56fe.mmd',
            'graph TD\n'
            '    A[项目经理]:::start --> B[技术负责人]:::mgmt\n'
            '    A --> C[安全质量负责人]:::mgmt\n'
            '    B --> D[施工员]:::tech\n'
            '    C --> D\n'
            '    B --> E[资料员]:::tech\n'
            '    D --> F[各专业班组]:::team\n'
            '    classDef start fill:#2563eb,color:#fff\n'
            '    classDef mgmt fill:#1d4ed8,color:#fff\n'
            '    classDef tech fill:#f59e0b,color:#000\n'
            '    classDef team fill:#16a34a,color:#fff\n')

        # 3. Emergency flowchart (universal)
        self._write('\u5e94\u6025\u6d41\u7a0b\u56fe.mmd',
            'graph TD\n'
            '    A[险情发生]:::emergency --> B{评估等级}:::decision\n'
            '    B -->|黄色| C[停止作业+加固]:::action\n'
            '    B -->|橙/红色| D[全面停工+撤离]:::action\n'
            '    C --> E[动态监测]:::process\n'
            '    D --> E\n'
            '    E --> F{控制?}:::decision\n'
            '    F -->|否| G[升级+119/120]:::emergency\n'
            '    F -->|是| H[应急终止+恢复]:::finish\n'
            '    G --> E\n'
            '    classDef emergency fill:#dc2626,color:#fff\n'
            '    classDef decision fill:#f59e0b,color:#000\n'
            '    classDef action fill:#2563eb,color:#fff\n'
            '    classDef process fill:#2563eb,color:#fff\n'
            '    classDef finish fill:#16a34a,color:#fff\n')

        # 4. Quality system chart (universal)
        print(f'  Flowchart type: {selected_flowchart} (project types: {", ".join(ptypes)})')
        self._write('\u8d28\u91cf\u4f53\u7cfb\u56fe.mmd',
            'graph TD\n'
            '    subgraph \u76ee\u6807\u5c42\n'
            '        A[\u8d28\u91cf\u76ee\u6807: \u5408\u683c\u5de5\u7a0b]:::start\n'
            '    end\n'
            '    subgraph \u7ba1\u7406\u5c42\n'
            '        B[\u9879\u76ee\u7ecf\u7406\u7b2c\u4e00\u8d23\u4efb\u4eba]:::mgmt --> C[\u6280\u672f\u8d1f\u8d23\u4eba]:::mgmt\n'
            '        B --> D[\u8d28\u91cf\u8d1f\u8d23\u4eba]:::mgmt\n'
            '    end\n'
            '    subgraph \u5236\u5ea6\u5c42\n'
            '        E[\u6280\u672f\u4ea4\u5e95]:::sys --> F[\u4e09\u68c0\u5236\u5ea6]:::sys\n'
            '        F --> G[\u6750\u6599\u9a8c\u6536]:::sys\n'
            '        G --> H[\u9690\u853d\u9a8c\u6536]:::sys\n'
            '        H --> I[\u8d28\u91cf\u4f8b\u4f1a]:::sys\n'
            '        I --> J[\u6574\u6539\u5236\u5ea6]:::sys\n'
            '    end\n'
            '    subgraph \u8fc7\u7a0b\u5c42\n'
            '        K[\u5de5\u5e8f\u8d28\u91cf\u63a7\u5236\u70b9]:::process --> L[PDCA\u5faa\u73af]:::process\n'
            '    end\n'
            '    subgraph \u9a8c\u6536\u5c42\n'
            '        M[\u68c0\u9a8c\u6279\u9a8c\u6536]:::finish --> N[\u5206\u9879\u9a8c\u6536]:::finish\n'
            '        N --> O[\u5206\u90e8\u9a8c\u6536]:::finish\n'
            '        O --> P[\u5355\u4f4d\u5de5\u7a0b\u9a8c\u6536]:::finish\n'
            '    end\n'
            '    A --> B\n'
            '    D --> E\n'
            '    J --> K\n'
            '    L --> M\n'
            '    classDef start fill:#2563eb,color:#fff\n'
            '    classDef mgmt fill:#1d4ed8,color:#fff\n'
            '    classDef sys fill:#f59e0b,color:#000\n'
            '    classDef process fill:#f59e0b,color:#000\n'
            '    classDef finish fill:#16a34a,color:#fff\n')

    def _write(self, filename, content):
        path = os.path.join(self.content_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)


if __name__ == '__main__':
    import argparse as _ap
    _parser = _ap.ArgumentParser()
    _parser.add_argument('brief', nargs='?', default='project_brief.md', help='Project brief file')
    _parser.add_argument('content_dir', nargs='?', default='content', help='Content directory')
    _parser.add_argument('--project', '-p', help='Project name for isolation (uses projects/<name>/content/)')
    _a = _parser.parse_args()

    content_dir = _a.content_dir
    if _a.project:
        skill_dir = os.path.dirname(os.path.dirname(__file__))
        content_dir = os.path.join(skill_dir, 'projects', _a.project, 'content')
        os.makedirs(content_dir, exist_ok=True)

    gen = ContentGenerator(_a.brief, content_dir)
    gen.generate_all()
