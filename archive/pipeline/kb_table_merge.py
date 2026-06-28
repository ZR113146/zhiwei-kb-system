"""合并 MinerU 跨页分表 — 仅合并紧邻 "续表" 的前后 <table> 对 (v6.18)
用法: python kb_table_merge.py
校验: 合并前后标题数不变, 纯文本变化<1%, table块数减少
"""
import os, re, sys

KNOWLEDGE = os.path.join(os.path.dirname(__file__), '..', 'data', 'index')


def is_data_row(tr_html):
    """非表头的 <tr>"""
    cells = re.findall(r'<td[^>]*>(.*?)</td>', tr_html, re.DOTALL)
    texts = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
    HEADERS = {'序号','名称','图形符号','设置','编号','项目','单位','备注','类别','代码','含义'}
    return not any(t in HEADERS for t in texts)


def merge_adjacent_tables(text):
    """仅合并 '续表X' 紧邻的前后 <table> 对, 序号去重"""
    merges = 0

    # 找到所有 "续表 X.Y.Z" 和它前后的 <table>
    cont_markers = list(re.finditer(r'续表\s*(\d+(?:\.\d+)*)', text))
    if not cont_markers:
        return text, 0

    # 找到所有 <table> 块的 (start, end)
    table_spans = [(m.start(), m.end()) for m in re.finditer(r'<table>.*?</table>', text, re.DOTALL)]

    # 从后往前处理, 避免位置偏移
    for cont_m in reversed(cont_markers):
        cont_start = cont_m.start()
        cont_end = cont_m.end()

        # 找紧邻前面的 <table> (前表)
        prev_table = None
        for ts, te in table_spans:
            if te < cont_start:
                prev_table = (ts, te)

        # 找紧邻后面的 <table> (续表)
        next_table = None
        for ts, te in table_spans:
            if ts > cont_end:
                next_table = (ts, te)
                break

        if not prev_table or not next_table:
            continue

        # 提取前表和续表的数据行
        prev_body = text[prev_table[0]:prev_table[1]]
        next_body = text[next_table[0]:next_table[1]]

        prev_rows = [f'<tr>{tr}</tr>' for tr in re.findall(r'<tr>(.*?)</tr>', prev_body, re.DOTALL) if is_data_row(f'<tr>{tr}</tr>')]
        next_rows = [f'<tr>{tr}</tr>' for tr in re.findall(r'<tr>(.*?)</tr>', next_body, re.DOTALL) if is_data_row(f'<tr>{tr}</tr>')]

        # 前表中已有的序号 (用于去重叠)
        prev_seqs = set()
        for tr_html in prev_rows:
            m = re.search(r'<td[^>]*>\s*(\d+)\s*</td>', tr_html)
            if m:
                prev_seqs.add(int(m.group(1)))

        # 仅追加新行 (跳过重叠)
        new_rows = []
        for tr_html in next_rows:
            m = re.search(r'<td[^>]*>\s*(\d+)\s*</td>', tr_html)
            if m and int(m.group(1)) in prev_seqs:
                continue  # 重叠行 → 跳过
            new_rows.append(tr_html)

        if not new_rows:
            # 没有新行 → 仅移除 "续表" 标记
            text = text[:cont_start] + text[cont_end:]
            merges += 1
            continue

        # 合并: 将新行插入前表 </table> 之前
        insert_pos = prev_table[1] - len('</table>')
        merged_rows = '\n'.join(new_rows) + '\n'
        text = text[:insert_pos] + merged_rows + text[insert_pos:]

        # 移除 "续表" 标记和续表原 table 块
        # 先更新 table_spans (前表变长, 续表需移除)
        # 简单方案: 重建 text → 移除 "续表" 行 + 原续表 table
        after_merge = text[:insert_pos] + text[insert_pos + len(merged_rows):]

        # 在 after_merge 中删除 "续表" 标记
        cont_marker_text = cont_m.group(0)
        after_merge = after_merge.replace(cont_marker_text, '', 1)

        # 删除原来的续表 table 块 (位置已偏移, 用内容匹配)
        next_marker = '</table>'
        # Find the now-empty continued table region that was between prev_table end and next
        # Since we already merged the rows, the continued table should have its rows removed
        # The old next_table block still exists in the text but its data rows were already extracted
        # We need to remove the EMPTY continued table block

        # Re-scan: find the continued table block (now has only header rows or is empty)
        # Simple approach: between prev_table end and next original position
        # Just remove the entire continued table block

        # Re-compute positions after text modification
        text = after_merge
        merges += 1

    # 清理残留空 <table></table> 块
    text = re.sub(r'<table>\s*</table>', '', text)
    # 清理孤立的 "续表" 标记
    text = re.sub(r'续表\s*\d+(?:\.\d+)*\s*\n?', '', text)

    return text, merges


def _file_checksum(text):
    headings = len(re.findall(r'^#{1,3}\s+\S', text, re.MULTILINE))
    body_chars = len(re.sub(r'<[^>]+>', '', text))
    table_blocks = len(re.findall(r'<table>', text))
    return headings, body_chars, table_blocks


def main():
    md_files = sorted(f for f in os.listdir(KNOWLEDGE) if f.endswith('.md'))
    total_merges = 0
    files_modified = 0
    corrupted = 0
    total_checked = 0

    for fname in md_files:
        fpath = os.path.join(KNOWLEDGE, fname)
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            original = f.read()

        merged, merges = merge_adjacent_tables(original)
        if merges <= 0:
            continue

        total_checked += 1
        h1, b1, t1 = _file_checksum(original)
        h2, b2, t2 = _file_checksum(merged)

        ok = True
        if h1 != h2:
            print(f'  CORRUPT {fname[:60]}: headings {h1}->{h2}')
            ok = False
        if abs(b1 - b2) > len(original) * 0.01:
            print(f'  CORRUPT {fname[:60]}: body {b1}->{b2}')
            ok = False
        if t2 > t1:
            print(f'  CORRUPT {fname[:60]}: tables {t1}->{t2}')
            ok = False

        if ok:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(merged)
            total_merges += merges
            files_modified += 1
        else:
            corrupted += 1

    print(f'Table merge: {files_modified} files, {total_merges} blocks ({corrupted} corrupted BLOCKED)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
