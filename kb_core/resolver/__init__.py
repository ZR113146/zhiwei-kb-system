# -*- coding: utf-8 -*-
"""kb_core.resolver: KBResolver 检索核心的分模块实现。

对外入口仍是 kb_core/kb_resolver_core.py (门面), 它从本包组装 KBResolver 并
re-export 公开符号, 保持 `from kb_resolver_core import KBResolver, normalize_code, ...`
等历史导入不变。本包内部模块通过 `from ._common import *` 共享前导层, 避免循环依赖。
"""
