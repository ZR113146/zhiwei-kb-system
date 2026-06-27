# -*- coding: utf-8 -*-
"""施工方案编制构建脚本：content -> docx，支持项目隔离。"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(__file__))
from render_engine import PlanRenderer

SKILL_DIR = os.path.dirname(os.path.dirname(__file__))
DEFAULT_CONTENT = os.path.join(SKILL_DIR, 'content')
_USERPROFILE = os.environ.get('USERPROFILE', os.path.expanduser('~'))
DEFAULT_OUTPUT = os.path.join(_USERPROFILE, 'Desktop', '\u65bd\u5de5\u65b9\u6848_\u8f93\u51fa.docx')


def resolve_project(name):
    """Resolve project directory: projects/<name>/content, fallback to shared content/"""
    if not name:
        return DEFAULT_CONTENT
    proj_dir = os.path.join(SKILL_DIR, 'projects', name, 'content')
    if os.path.isdir(proj_dir):
        return proj_dir
    os.makedirs(proj_dir, exist_ok=True)
    print(f'  Created: {proj_dir}')
    copied_any = False
    for ch in ['ch01','ch02','ch03','ch04','ch05','ch06','ch07','ch08','ch09']:
        src = os.path.join(DEFAULT_CONTENT, f'{ch}.md')
        dst = os.path.join(proj_dir, f'{ch}.md')
        if os.path.exists(src) and not os.path.exists(dst):
            import shutil
            shutil.copy2(src, dst)
            copied_any = True
    if not copied_any:
        has_content = any(os.path.exists(os.path.join(proj_dir, f'{ch}.md'))
                        for ch in ['ch01','ch02','ch03','ch04','ch05','ch06','ch07','ch08','ch09'])
        if not has_content:
            import logging
            logging.warning('Project directory has no chapter files; run content_generator.py first to create ch01.md')
    return proj_dir


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', '-p', help='Project name for isolation (uses projects/<name>/content/)')
    parser.add_argument('--output', '-o', help='Output docx path')
    parser.add_argument('--template', '-t', help='Template name (default: default.json)')
    args = parser.parse_args()

    content_dir = resolve_project(args.project)
    output_path = args.output
    if not output_path:
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(_USERPROFILE, 'Desktop', f'施工方案_{ts}.docx')

    if args.project and not args.output:
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(_USERPROFILE, 'Desktop', f'{args.project}_施工方案_{ts}.docx')

    PlanRenderer(content_dir, output_path, template_name=args.template).build()
