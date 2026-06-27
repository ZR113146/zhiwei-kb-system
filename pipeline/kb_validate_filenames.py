"""PDF 文件命名规范校验 + 批量修正 — Phase A 前置检查
用法:
  python kb_validate_filenames.py "<规范PDF目录>"          # 仅检测
  python kb_validate_filenames.py "<规范PDF目录>" --fix    # 检测 + 自动修正
"""
import os, re, sys
from collections import defaultdict

# ── 标准编号正则 (与 pipeline_orchestrator 同步) ──
CODE_RE = re.compile(
    r'((?:GB|JGJ|CJJ|CECS|CJ|DB|JTG|TCECS|JC|RISN)(?:\d+)?\s*[/／_]?\s*T?\s*[-]?\s*[A-Z]{0,3}\d+[\.-]\d+(?:-\d+)?)',
    re.IGNORECASE
)

# ── 需空格分隔的已知前缀 ──
SPACE_PREFIXES = ['GB', 'JGJ', 'CJJ', 'CECS', 'CJ', 'JTG']

# ═══════════════════════ 校验 ═══════════════════════

def validate_filename(fn):
    """返回 (problems: list[str], warnings: list[str])"""
    name = fn[:-4] if fn.lower().endswith('.pdf') else fn
    ext = fn[-4:] if fn.lower().endswith('.pdf') else ''
    p = []
    w = []

    if '  ' in name:
        p.append('含双空格')

    if ext and name.endswith(' '):
        p.append('扩展名前有空格')

    if ext == '.PDF':
        p.append('扩展名大写 .PDF → 应为 .pdf')

    m = CODE_RE.search(fn)
    if m:
        code_end = m.end()
        if code_end < len(name) and not name[code_end].isspace() and not name[code_end] in '\uff08(':
            if '\u4e00' <= name[code_end] <= '\u9fff':
                p.append('编号后缺空格: %s后直接接中文' % m.group(1)[:15])

    for prefix in SPACE_PREFIXES:
        m2 = re.match(r'^(' + prefix + r')(\d{2,6})', name)
        if m2 and not name.startswith(prefix + 'T'):
            p.append('字母数字间缺空格: %s%s → %s %s' % (m2.group(1), m2.group(2), m2.group(1), m2.group(2)))
            break

    if '\u2014' in name or '\u2013' in name or '\uff0d' in name:
        p.append('含中文破折号 (应为 ASCII -)')
    if '\u2215' in name:
        p.append('含Unicode除号 \u2215 (应为 ASCII / 或 _)')
    if '\uff5e' in name:
        p.append('含全角波浪号 \uff5e (应为 -)')

    h_open = name.count('('); h_close = name.count(')')
    f_open = name.count('\uff08'); f_close = name.count('\uff09')
    if h_open != h_close:
        p.append('英文括号不配对: %d开 %d闭' % (h_open, h_close))
    if f_open != f_close:
        p.append('中文括号不配对: %d开 %d闭' % (f_open, f_close))
    if h_open > 0 and f_close > 0:
        p.append('英文( 配 中文）')
    if f_open > 0 and h_close > 0:
        p.append('中文（ 配 英文)')

    if re.match(r'^\d{4}[\.\-\/]\d{1,2}[\.\-\/]\d{1,2}', name):
        w.append('文件名以日期开头，建议改为标准编号开头')

    if '副本' in name or '拷贝' in name:
        w.append('疑似重复副本')

    if re.search(r'\d_[^\d]', name) and '_T' not in name:
        p.append('下划线应替换为空格')

    return p, w


# ═══════════════════════ 批量修正 ═══════════════════════

def fix_filename(fn):
    """修正命名问题，返回 (new_name, fixes_applied)"""
    base, ext = os.path.splitext(fn)
    new = base
    fixes = []

    # 1. 特殊Unicode字符
    if '\u2215' in new:
        new = new.replace('\u2215', '_')
        fixes.append('\u2215→_')
    if '\uff5e' in new:
        new = new.replace('\uff5e', '-')
        fixes.append('\uff5e→-')
    if '\u2014' in new:
        new = new.replace('\u2014', '-')
        fixes.append('\u2014→-')
    if '\u2013' in new:
        new = new.replace('\u2013', '-')
        fixes.append('\u2013→-')

    # 2. 多空格→单空格
    while '  ' in new:
        new = new.replace('  ', ' ')
        fixes.append('双空格→单')

    # 3. 去除尾部空格
    if new.endswith(' '):
        new = new.rstrip()
        fixes.append('尾部空格去除')

    # 4. 扩展名规范化: .PDF → .pdf
    if fn.endswith('.PDF'):
        ext = '.pdf'

    # 5. 扩展名前多余空格
    if ext == '.pdf' and fn.endswith(' .pdf'):
        new = new.rstrip()

    # 6. 字母数字间插入空格 (GB50011 → GB 50011, 仅已知前缀)
    for prefix in SPACE_PREFIXES:
        m = re.match(r'^(' + prefix + r')(\d{2,6})', new)
        if m and not new.startswith(prefix + 'T'):
            rest = new[m.end():]
            new = prefix + ' ' + m.group(2) + rest
            fixes.append('%s%s→%s %s' % (prefix, m.group(2), prefix, m.group(2)))
            break

    # 7. 年份后插入空格 (2015混凝土 → 2015 混凝土)
    new = re.sub(r'(\d{4})([\u4e00-\u9fff])', r'\1 \2', new)

    # 8. 中文括号前多余空格
    new = re.sub(r' \uff08', '\uff08', new)

    # 9. 括号配对修正: 英文( 配 中文） → 统一中文
    if '(' in new and '\uff09' in new:
        new = new.replace('(', '\uff08')
        fixes.append('英文(→中文（')
    if '\uff08' in new and ')' in new:
        new = new.replace(')', '\uff09')
        fixes.append('英文)→中文）')

    # 10. 下划线用作空格 (14S501-1_铸铁 → 14S501-1 铸铁)
    m_under = re.search(r'(\d[\-\.]\d+)_([\u4e00-\u9fff])', new)
    if m_under:
        new = new[:m_under.end(1)] + ' ' + new[m_under.end(1)+1:]
        fixes.append('_→空格')

    # 11. JGJ-59 → JGJ 59
    m_jgj = re.match(r'^(JGJ)-(\d{1,3}-\d{4})', new)
    if m_jgj:
        new = 'JGJ ' + m_jgj.group(2) + new[m_jgj.end():]
        fixes.append('JGJ-→JGJ ')

    return new + ext, fixes


def collect_files(srcdir):
    """递归收集所有 PDF"""
    files = []
    for root, dirs, fnames in os.walk(srcdir):
        for fn in fnames:
            if fn.lower().endswith('.pdf'):
                files.append(os.path.join(root, fn))
    return files


def check_directory(srcdir, do_fix=False):
    """扫描目录，校验并可选修正所有 PDF 文件名"""
    if not os.path.isdir(srcdir):
        print('目录不存在: %s' % srcdir)
        return 1

    flat = [f for f in os.listdir(srcdir) if f.lower().endswith('.pdf')]
    if flat:
        all_pdfs = [os.path.join(srcdir, f) for f in sorted(flat)]
    else:
        all_pdfs = sorted(collect_files(srcdir))
        flat = [os.path.basename(p) for p in all_pdfs]

    print('=' * 60)
    if do_fix:
        print('PDF 命名规范校验 + 自动修正: %s' % srcdir)
    else:
        print('PDF 命名规范校验: %s' % srcdir)
    print('文件数: %d' % len(all_pdfs))
    print('=' * 60)

    # ── 重复检测 ──
    codes = defaultdict(list)
    for fp in all_pdfs:
        fn = os.path.basename(fp)
        m = CODE_RE.search(fn)
        if m:
            code = m.group(1).replace(' ', '').replace('\uff0f', '/').replace('_T', 'T')
            codes[code].append(fp)

    dups = {c: fs for c, fs in codes.items() if len(fs) > 1}
    if dups:
        print('\n[重复标准编号]')
        for code, files in dups.items():
            s = os.path.getsize
            print('  %s: %d 文件' % (code, len(files)))
            for fp in files:
                print('    [%.1fMB] %s' % (os.path.getsize(fp)/1024/1024, os.path.basename(fp)))

    # ── 逐文件校验 ──
    errors = []; warns = []; ok_count = 0

    print()
    for fp in all_pdfs:
        fn = os.path.basename(fp)
        problems, warnings = validate_filename(fn)
        if problems:
            errors.append((fp, fn, problems))
        elif warnings:
            warns.append((fp, fn, warnings))
        else:
            ok_count += 1

    # ── 报告 ──
    if errors:
        print('[错误] %d 个文件:' % len(errors))
        for fp, fn, probs in errors:
            print('  %s' % fn)
            for prob in probs:
                print('    -> %s' % prob)
        print()

    if warns:
        print('[警告] %d 个文件:' % len(warns))
        for fp, fn, wrns in warns:
            print('  %s' % fn)
            for w in wrns:
                print('    ~ %s' % w)
        print()

    print('通过: %d  错误: %d  警告: %d' % (ok_count, len(errors), len(warns)))

    # ── 修正 ──
    if do_fix and errors:
        print()
        print('─' * 40)
        print('自动修正中...')
        print('─' * 40)
        fixed_count = 0
        for fp, fn, probs in errors:
            new_fn, fix_list = fix_filename(fn)
            if new_fn != fn:
                new_path = os.path.join(os.path.dirname(fp), new_fn)
                if os.path.exists(new_path) and new_path != fp:
                    print('  跳过(目标已存在): %s' % fn)
                    continue
                try:
                    os.rename(fp, new_path)
                    print('  [%s]' % ', '.join(fix_list))
                    print('    %s -> %s' % (fn, new_fn))
                    fixed_count += 1
                except Exception as e:
                    print('  失败: %s — %s' % (fn, e))
            else:
                print('  无法自动修正: %s' % fn)
        print()
        print('修正完成: %d/%d' % (fixed_count, len(errors)))

        # 修正后复检
        if fixed_count > 0:
            print()
            print('复检...')
            return check_directory(srcdir, do_fix=False)

    if errors:
        if do_fix:
            print('\n仍有未修正错误，请手动处理。')
        else:
            print('\n请修正后重新入库。提示: 加 --fix 可自动修正。')
        return 1
    elif warns:
        print('警告项不阻塞入库。')
        return 0
    else:
        print('全部通过。')
        return 0


if __name__ == '__main__':
    do_fix = '--fix' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--fix']
    if len(args) < 1:
        print('用法: python kb_validate_filenames.py <PDF目录> [--fix]')
        print('  --fix  自动修正检测到的命名问题')
        sys.exit(1)
    sys.exit(check_directory(args[0], do_fix=do_fix))
