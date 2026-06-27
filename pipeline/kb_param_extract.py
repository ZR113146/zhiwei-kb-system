"""高频参数提取 — 从 KB 文件中提取参数→数值→条款映射
输出: data/kb_json/kb_param_index.json
用法: python kb_param_extract.py
"""
import json, os, re

KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')
OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'kb_json', 'kb_param_index.json')

# Parameter patterns: (param_name, regex_list)
# Each regex should capture: value, condition (optional)
PARAM_PATTERNS = [
    ('保护层厚度', [
        r'保护层厚度.{0,20}不[应得][小大少于]{1,2}\s*(\d+)\s*(mm|cm)',
        r'保护层厚度.{0,20}(\d+)\s*(mm|cm)',
    ]),
    ('混凝土强度等级', [
        r'(?:混凝土)?强度等级.{0,10}(?:不应低于|不低于|应为)\s*(C\d+)',
    ]),
    ('施工缝间距', [
        r'施工缝.{0,30}(?:间距|距离).{0,10}(?:不宜大于|不应大于|不大于)\s*(\d+)\s*(m|mm)',
    ]),
    ('养护时间', [
        r'(?:养护|浇水养护).{0,20}(?:不少于|不应少于|不得少于|至少)\s*(\d+)\s*(天|d|h|小时)',
    ]),
    ('锚固长度', [
        r'(?:锚固长度|锚固).{0,20}(?:不应小于|不小于|应大于)\s*(\d+)\s*(d|mm)',
    ]),
    ('防水层厚度', [
        r'(?:防水层|防水涂膜).{0,20}(?:厚度|厚).{0,10}(?:不应小于|不小于)\s*(\d+\.?\d*)\s*(mm)',
    ]),
    ('搭接宽度', [
        r'(?:搭接|搭接缝).{0,20}(?:宽度|宽).{0,10}(?:不应小于|不小于|宜为)\s*(\d+)\s*(mm|cm)',
    ]),
    ('坍落度', [
        r'坍落度.{0,30}(?:应为|宜为|控制在)\s*(\d+\.?\d*)\s*~?\s*(\d+\.?\d*)?\s*(mm|cm)',
    ]),
    ('防火极限', [
        r'(?:耐火极限|防火极限).{0,20}(?:不应低于|不低于|不应小于)\s*(\d+\.?\d*)\s*(h|min)',
    ]),
    ('除锈等级', [
        r'除锈.{0,10}(?:等级|质量).{0,20}(?:达到|应符合|满足)\s*(Sa\d+(?:\.?\d+)?|St\d+)',
    ]),
    ('焊缝检测比例', [
        r'(?:焊缝|探伤).{0,30}(?:比例|抽检).{0,10}(?:不少于|不低于|不应少于)\s*(\d+)\s*(%|％)',
    ]),
    ('砂浆强度等级', [
        r'(?:砂浆|砌筑砂浆).{0,10}强度等级.{0,10}(?:不应低于|不低于|应为)\s*(M\d+\.?\d*)',
    ]),
    ('回弹法检测', [
        r'回弹法.{0,30}(?:测区|检测).{0,20}(?:不少于|不应少于)\s*(\d+)\s*(个|点)',
    ]),
    ('疏散宽度', [
        r'(?:疏散|安全出口).{0,10}(?:宽度|净宽).{0,10}(?:不应小于|不小于)\s*(\d+\.?\d*)\s*(m)',
    ]),
    ('模板拆除', [
        r'(?:拆模|模板拆除).{0,30}(?:强度|混凝土强度).{0,10}(?:达到|不低于)\s*(\d+\.?\d*)\s*(%|％|MPa)',
    ]),
]

def extract_params():
    md_files = sorted([f for f in os.listdir(KB_DIR) if f.endswith('.md') and f != 'kb_search_index.json'])

    results = {}
    total_hits = 0

    for fn in md_files:
        fp = os.path.join(KB_DIR, fn)
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            continue

        code_m = re.search(r'(GB|JGJ|CJJ|CECS|TCECS|JC|DB|JTG|RISN)[\sT/_]?\d+[\.\-]?\d*', fn)
        std_code = code_m.group(0).replace(' ','').replace('_','/') if code_m else fn[:30]

        for param_name, patterns in PARAM_PATTERNS:
            for pat in patterns:
                for m in re.finditer(pat, content):
                    value = m.group(1) or ''
                    unit = m.group(2) or '' if m.lastindex and m.lastindex >= 2 else ''
                    condition = m.group(3) or '' if m.lastindex and m.lastindex >= 3 else ''

                    # Find nearest heading before this position
                    heading = ''
                    clause_num = ''
                    # Simple: use the closest section start
                    si = json.load(open(os.path.join(KB_DIR, 'kb_search_index.json'), 'r', encoding='utf-8'))
                    if fn in si['index']:
                        for s in reversed(si['index'][fn]):
                            if s['pos'] <= m.start():
                                heading = s.get('heading', '')
                                cm = re.match(r'^(\d+(?:\.\d+)*)\s', heading)
                                if cm:
                                    clause_num = cm.group(1)
                                break

                    if param_name not in results:
                        results[param_name] = []

                    entry = {
                        'value': value + unit,
                        'std_code': std_code,
                        'clause': clause_num,
                        'heading': heading[:60],
                        'condition': condition
                    }

                    # Dedup
                    if entry not in results[param_name]:
                        results[param_name].append(entry)
                        total_hits += 1

    output = {'params': results}
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    print('Param index: %d params, %d entries, %.1fKB' % (
        len(results), total_hits, os.path.getsize(OUTPUT)/1024))
    for name, entries in sorted(results.items(), key=lambda x: -len(x[1])):
        print('  %s: %d entries' % (name, len(entries)))

if __name__ == '__main__':
    extract_params()
