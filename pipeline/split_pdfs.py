"""PDF 批量切割：按页数切分超大 PDF。支持单文件 + 目录批量。

切割策略（三维综合）：
  触发条件：pages > 200  OR  size > 200MB (VLM API限制)
  自动计算：N = max(ceil(pages/200), ceil(size_mb/10))
  页数均分：每块 = ceil(pages / N)，最后一块补齐
  结果保证：每块 ≤200页 且 ≈size/N ≤200MB (VLM限制)

用法:
  python split_pdfs.py "文件.pdf"                  # 单文件切割（自动计算最优分块）
  python split_pdfs.py "文件.pdf" -p 100           # 强制指定每块页数
  python split_pdfs.py --dir "目录"                # 目录批量（逐文件自动计算）
  python split_pdfs.py --dir "目录" -p 80          # 目录批量 + 统一页数
"""
import os, sys, argparse, math
from contextlib import redirect_stderr
from pypdf import PdfReader, PdfWriter

def _read_pdf(path):
    """读取PDF，抑制pypdf内部stderr警告"""
    with redirect_stderr(open(os.devnull, 'w')):
        return PdfReader(path)

# ---- 统一配置（kb.json）----
_KB_DIR = os.path.join(os.path.dirname(__file__), '..', 'kb_core')
if _KB_DIR not in sys.path:
    sys.path.insert(0, _KB_DIR)
from kb_core.kb import load_config
import kb_core.changelog as changelog; changelog.record(__file__, sys.argv)
DEFAULT_OUT = load_config()['paths']['staging']


def auto_chunk_pages(total_pages, size_mb, max_pages=200, max_size_mb=200):
    """三维切割策略：根据页数+大小自动计算最优每块页数。

    保证结果：
      - 每块 ≤200页
      - 每块 ≈原始大小/块数 ≤最大上传限制
      - 页数尽量均分，不浪费 API 调用

    返回: (pages_per_chunk, n_chunks)
    """
    n_for_pages = math.ceil(total_pages / max_pages)
    n_for_size = math.ceil(size_mb / max_size_mb)
    n_chunks = max(n_for_pages, n_for_size, 1)
    pages_per = math.ceil(total_pages / n_chunks)
    return pages_per, n_chunks


def split_pdf(pdf_path, out_dir=DEFAULT_OUT, pages_per_chunk=100, max_size_mb=200):
    """切分单个 PDF，含超标复检。

    先按 pages_per_chunk 初切，每块写出后量实际大小。
    若超过 max_size_mb 则拆半重切（递归），保证最终每块 ≤ 阈值。
    返回 (chunks: int, total_pages: int, error: str|None)
    """
    try:
        reader = _read_pdf(pdf_path)
    except Exception as e:
        return 0, 0, str(e)

    total = len(reader.pages)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    chunks = 0
    re_split_count = 0

    # 用队列处理：初切分段入队，写后超标则拆半重新入队
    segments = [(s, min(s + pages_per_chunk, total)) for s in range(0, total, pages_per_chunk)]

    while segments:
        start, end = segments.pop(0)
        try:
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            out_name = f'{base}_p{start+1:04d}-{end:04d}.pdf'
            out_path = os.path.join(out_dir, out_name)
            with open(out_path, 'wb') as f:
                writer.write(f)

            size_kb = os.path.getsize(out_path) / 1024
            size_mb = size_kb / 1024
            pages = end - start

            if size_mb > max_size_mb and pages > 2:
                # 超标：删文件，拆半重新入队
                os.remove(out_path)
                mid = start + pages // 2
                segments.insert(0, (mid, end))
                segments.insert(0, (start, mid))
                re_split_count += 1
                print(f'  [WARN] {out_name} ({size_kb:.0f}KB) 超标, 拆半重切')
            else:
                print(f'  {out_name} ({size_kb:.0f}KB, {pages}页)')
                chunks += 1
        except Exception as e:
            print(f'  错误: 页{start+1}-{end} 写入失败: {e}')

    if re_split_count:
        print(f'  复检: {re_split_count} 块超标已拆半重切')
    return chunks, total, None


def process_single(pdf_path, out_dir, pages_per_chunk=None):
    """处理单个 PDF：判断是否需要切割。

    pages_per_chunk=None → 自动计算最优分块（三维策略）
    pages_per_chunk=int  → 强制指定每块页数
    """
    if not os.path.exists(pdf_path):
        print(f'文件不存在: {pdf_path}')
        return False, 'missing'

    os.makedirs(out_dir, exist_ok=True)

    try:
        reader = _read_pdf(pdf_path)
        total = len(reader.pages)
    except Exception as e:
        print(f'{os.path.basename(pdf_path)}: 无法读取 ({e})')
        return False, 'corrupt'

    size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    print(f'{os.path.basename(pdf_path)}: {total}页, {size_mb:.1f}MB')

    if total <= 200 and size_mb <= 200:
        print(f'  → 无需切割（≤200页且≤200MB，VLM限制内）')
        return True, 'skip'

    # 自动计算最优分块（三维策略）
    if pages_per_chunk is None:
        pages_per_chunk, n = auto_chunk_pages(total, size_mb)
        est_mb = size_mb / n
        print(f'  → 自动计算: {pages_per_chunk}页/块 × {n}块 (≈{est_mb:.1f}MB/块)')
    else:
        n = None  # 手动模式不显示块数预估

    _, _, err = split_pdf(pdf_path, out_dir, pages_per_chunk)
    if err:
        print(f'  错误: {err}')
        return False, 'error'
    print(f'  完成: 每块 ≤{pages_per_chunk}页')
    return True, 'split'


def process_directory(dir_path, out_dir, pages_per_chunk=None):
    """扫描目录，对所有需切割的 PDF 执行切割"""
    pdfs = [f for f in os.listdir(dir_path) if f.endswith('.pdf')]
    if not pdfs:
        print(f'目录中无 PDF: {dir_path}')
        return

    print(f'扫描: {len(pdfs)} 个 PDF')
    stats = {'split': 0, 'skip': 0, 'error': 0, 'corrupt': 0}

    for fname in sorted(pdfs):
        fpath = os.path.join(dir_path, fname)
        success, reason = process_single(fpath, out_dir, pages_per_chunk)
        if success:
            if reason == 'split':
                stats['split'] += 1
            else:
                stats['skip'] += 1
        else:
            stats[reason] = stats.get(reason, 0) + 1
        print()

    print(f'批量完成: {stats["split"]} 切割, {stats["skip"]} 跳过, '
          f'{stats.get("error",0)} 错误, {stats.get("corrupt",0)} 损坏')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='PDF批量切割')
    p.add_argument('pdf', nargs='?', help='PDF文件路径（单文件模式）')
    p.add_argument('-p', '--pages', type=int, default=None,
                   help='每块页数（默认自动计算：三维策略 min(200p, 200MB)）')
    p.add_argument('-o', '--out', default=DEFAULT_OUT,
                   help=f'输出目录（默认staging）')
    p.add_argument('--dir', metavar='DIR', help='目录批量模式')
    args = p.parse_args()

    if args.dir:
        process_directory(args.dir, args.out, args.pages)
    elif args.pdf:
        success, reason = process_single(args.pdf, args.out, args.pages)
        sys.exit(0 if success else 1)
    else:
        p.print_help()
