# -*- coding: utf-8 -*-
"""resolver.naming: KBResolver 的标准名称解析与 MD 文件定位 mixin。

从 kb_resolver_core 拆出的"标准名/文件名"方法组 (从文件名/正文/内容解析标准
中文名, 以及按编码定位 MD 文件)。作为 mixin 被 KBResolver 继承, 方法体逐字保留。
"""

import os, re

from ._common import KB_MD_DIR, normalize_code, normalize_status_code


class NamingMixin:

    def _parse_name_from_filename(self, fname):
        """L1: Extract standard Chinese name from MD filename.
        Handles: 'GB 50209-2010 建筑地面工程施工质量验收规范.md'
                 '_seg3_GB 50666-2011 混凝土结构工程施工规范_p0201-0220.md'
                 'CJJT 287-2018  园林绿化养护标准.md'"""
        base = fname.replace('.md', '')
        # Strip _segN_ prefix
        base = re.sub(r'^_seg\d+_', '', base)
        # Remove trailing _pXXXX-XXXX segment marker
        base = re.sub(r'_p\d{4}-\d{4}$', '', base)
        # Split: code part ends at first non-code alpha boundary after the year
        # Pattern: CODE_PREFIX NUMBER[-.]NUMBER[-NUMBER] REST
        m = re.match(
            r'(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|JTG|TCECS)[\s/_]*T?[\s_]*\d+[\.-]\d+(?:-\d+)?)\s+(.+)',
            base, re.IGNORECASE
        )
        if m:
            name = m.group(1).strip()
            # Remove page range suffixes like _p0201-0251 that weren't caught above
            name = re.sub(r'[\s_]*_?p\d{4}[_-]\d{4}$', '', name).strip()
            return name if name else None
        return None

    def _parse_name_from_body(self, md_path):
        """L2: Extract official standard name from document body.
        Sources (in priority order):
        1. YAML frontmatter title
        2. Standard declaration line: '标准编号 名称'
        3. First non-generic H1 heading
        4. Name following code on a separate line"""
        if not md_path or not os.path.exists(md_path):
            return None
        try:
            with open(md_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(8000)
        except Exception:
            return None

        # Source 1: YAML frontmatter title (highest priority)
        yaml_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if yaml_match:
            yaml = yaml_match.group(1)
            m = re.search(r'title:\s*["\']?([^"\'\n]{5,80})["\']?', yaml)
            if m:
                title = m.group(1).strip()
                # Strip standard code prefix
                title = re.sub(r'^(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?\s+', '', title)
                return title

        # Source 2: Standard declaration with code directly followed by name
        # Handles both "GB 50209-2010 建筑地面..." (with space) and "GB50204-2015混凝土..." (no space)
        m = re.search(
            r'(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s*'
            r'([\u4e00-\u9fff][\u4e00-\u9fff\s·]{3,50}?)(?:[\n\r]|"|\u201c|（|\()',
            content
        )
        if m:
            name = m.group(1).strip()
            if name not in self._GENERIC_TITLES:
                return name

        # Source 3: First non-generic H1 heading
        for m in re.finditer(r'^#\s+(.{3,80}?)(?:\n|$)', content, re.MULTILINE):
            h1 = m.group(1).strip()
            if h1 not in self._GENERIC_TITLES and \
               not re.match(r'^(前[言序]|目[次录]|总则|[0-9]+\.|附录|术语和|基本规定)', h1):
                return h1

        # Source 4: Code line followed by name on next line
        m = re.search(
            r'(?:GB|JGJ|CJJ|CECS|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?\s*\n'
            r'\s*#\s*([\u4e00-\u9fff][\u4e00-\u9fff\s·]{3,50})',
            content
        )
        if m:
            name = m.group(1).strip()
            if name not in self._GENERIC_TITLES:
                return name

        return None

    def _parse_name_from_content(self, standard_code):
        """L3: Deep search — read all segments, find most authoritative name.
        Used when L1/L2 fail or disagree."""
        nc = normalize_code(standard_code)
        md_files = self.find_all_md(standard_code)
        if not md_files:
            return None

        # Collect candidate names from all segments
        candidates = {}
        for md_path in md_files:
            if not md_path or not os.path.exists(md_path):
                continue
            try:
                with open(md_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(8000)
            except (IOError, OSError):
                continue

            # Find all occurrences of the code followed by a name
            for m in re.finditer(
                r'(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s+'
                r'([\u4e00-\u9fff][\u4e00-\u9fff\s·]{2,50}?)(?:[\n\r]|[（(]|"|\u201c)',
                content
            ):
                name = m.group(1).strip()
                # Filter garbage
                if len(name) >= 4 and not re.match(r'^[\s\d_\-\.,;]+$', name):
                    candidates[name] = candidates.get(name, 0) + 1

            # Also check for standard declaration patterns
            for m in re.finditer(
                r'(?:中华人民共和国国家标准|中华人民共和国行业标准|中国工程建设标准化协会标准)\s*\n'
                r'\s*((?:GB|JGJ|CJJ|CECS|TCECS)[\s/]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s+'
                r'([\u4e00-\u9fff][\u4e00-\u9fff\s·\-]{3,50})',
                content
            ):
                name = m.group(2).strip()
                if len(name) >= 4:
                    candidates[name] = candidates.get(name, 0) + 5  # Weight authoritative declarations higher

        if not candidates:
            return None

        # Return most frequent candidate
        return max(candidates, key=candidates.get)

    def get_name(self, standard_code):
        """Resolve standard code → official Chinese name. Three-layer fallback:
        L1: Parse MD filename (fast, 83 codes covered)
        L2: Extract from document body preamble (YAML→declaration→H1)
        L3: Deep content search across all segments (slow, last resort)

        Returns: (name: str, source_layer: int, confidence: str)
          confidence: 'high' (L1/L2 agree), 'medium' (single layer only), 'low' (L3 guess)
        """
        if not standard_code or not standard_code.strip():
            return None, 0, ''
        nc = normalize_code(standard_code)
        # GBT/GB equivalence: try alternate prefix

        l1_name = None
        l2_name = None

        # L1: from filename (try normalized code, status aliases, then GB/GBT alternate)
        for code_candidate in self._code_candidates(standard_code):
            if code_candidate in self.md_codes:
                l1_name = self._parse_name_from_filename(self.md_codes[code_candidate])
                if l1_name:
                    break
            # Fuzzy filename search
            for f in self.md_list:
                fn = normalize_code(f.replace('.md', ''))
                if code_candidate in fn or fn in code_candidate:
                    l1_name = self._parse_name_from_filename(f)
                    if l1_name:
                        break
            if l1_name:
                break

        # L2: from document body (find_md handles GBT/GB equivalence)
        md_path = self.find_md(standard_code)
        if md_path:
            l2_name = self._parse_name_from_body(md_path)

        # Determine confidence and return
        # Final name normalization
        def _clean_name(n):
            if not n:
                return n
            # Strip _segN_ prefix (segmented file artifact)
            n = re.sub(r'^_seg\d+_', '', n)
            # Strip leading code prefix (e.g. "GB 50204-2015混凝土..." or "JGJ-59-2011 建筑施工...")
            n = re.sub(r'^(?:(?:GB|JGJ|CJJ|CECS|CJ|DB|TCECS)[\s/\-]*T?\s*\d+[\.-]\d+(?:-\d+)?)\s*', '', n)
            # Strip page range suffix
            n = re.sub(r'_p\d{4}[_-]\d{4}$', '', n)
            # Strip version year suffix like "（2025年版）"
            n = re.sub(r'[（(]\d{4}年版[）)]', '', n).strip()
            return n.strip()

        if l1_name and l2_name:
            def _norm(s):
                return s.replace(' ', '').replace('·', '').replace('-', '').replace('（2025年版）', '')
            cn1 = _clean_name(l1_name)
            cn2 = _clean_name(l2_name)
            if _norm(cn1) == _norm(cn2):
                return cn1, 1, 'high'
            elif cn1 in cn2 or cn2 in cn1:
                return cn2 if len(cn2) >= len(cn1) else cn1, 2, 'high'
            else:
                return cn2, 2, 'medium'  # Body is more authoritative
        elif l1_name:
            return _clean_name(l1_name), 1, 'medium'
        elif l2_name:
            return _clean_name(l2_name), 2, 'medium'

        # L3: deep search
        l3_name = self._parse_name_from_content(standard_code)
        if l3_name:
            return l3_name, 3, 'low'

        return None, 0, 'not_found'

    def find_md(self, standard_code):
        """Find MD file path for a standard code. Returns best match (prefer non-seg, or first seg)"""
        code_candidates = self._code_candidates(standard_code)
        for code_candidate in code_candidates:
            if code_candidate in self.md_codes:
                return os.path.join(KB_MD_DIR, self.md_codes[code_candidate])
        matches = []
        for f in self.md_list:
            fn = normalize_code(f.replace('.md', ''))
            if fn and any(cc and (cc in fn or fn in cc) for cc in code_candidates):
                matches.append(os.path.join(KB_MD_DIR, f))
        return matches[0] if matches else None

    def find_all_md(self, standard_code):
        """Find ALL MD files for a standard (handles segmented files like _seg0, _seg1...)"""
        matches = []
        code_candidates = self._code_candidates(standard_code)
        for code_candidate in code_candidates:
            if code_candidate in self.md_codes:
                fp = os.path.join(KB_MD_DIR, self.md_codes[code_candidate])
                if fp not in matches:
                    matches.append(fp)
        for f in self.md_list:
            fn = normalize_code(f.replace('.md', ''))
            if fn and any(cc and (cc in fn or fn in cc) for cc in code_candidates):
                fp = os.path.join(KB_MD_DIR, f)
                if fp not in matches:
                    matches.append(fp)
        status_code = normalize_status_code(standard_code)
        for f in self.md_list:
            fn = normalize_status_code(f.replace('.md', '')) or normalize_code(f.replace('.md', ''))
            if status_code and fn == status_code:
                fp = os.path.join(KB_MD_DIR, f)
                if fp not in matches:
                    matches.append(fp)
        return matches

    def _extract_code_from_filename(self, fname):
        """Extract standard code from MD filename for project_standards matching.
        v6.18: 剥离尾部年份(19xx/20xx)防止 JGJ-59-2011 → JGJ592011 的粘合错误"""
        m = re.search(r'(GB\s*/?\s*T?|JGJ\s*T?|CJJ\s*T?|CECS|CJ\s*/?\s*T?|DB)\s*[-]?\s*\d+[\.-]\d+(?:-\d+)?', fname)
        if m:
            code = m.group()
            # 剥离尾部年份: JGJ-59-2011 → JGJ-59, GB50204-2015 → GB50204
            code = re.sub(r'[-](?:19|20)\d{2}$', '', code)
            return normalize_code(code)
        return None
