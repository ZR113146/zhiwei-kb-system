# -*- coding: utf-8 -*-
"""方案桥接层：对外暴露 build_plan / plan_status。"""

import sys, os

_ROOT = os.path.dirname(os.path.abspath(__file__))
_plan_writer = os.path.join(_ROOT, 'plan_writer')
_kb_core = os.path.join(_ROOT, 'kb_core')
_pipeline = os.path.join(_ROOT, 'pipeline')

for p in [_plan_writer, _pipeline, _ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)


class PlanBridge:
    def __init__(self):
        self._orchestrator = None

    def _load(self):
        if self._orchestrator is None:
            from orchestrator import Orchestrator
            self._orchestrator = Orchestrator()

    def build_plan(self, project_dir: str, output_dir: str = None, append_citation_summary: bool = False) -> dict:
        """Use python-docx rendering for plan generation."""
        self._load()
        return self._orchestrator.run(
            project_dir, output_dir or project_dir,
            append_citation_summary=append_citation_summary)

    def status(self) -> dict:
        return {
            'orchestrator': 'ready',
            'kb_core': os.path.exists(os.path.join(_kb_core, 'kb.json')),
            'pipeline': os.path.exists(os.path.join(_pipeline, 'pipeline_orchestrator.py')),
            'plan_writer': os.path.exists(os.path.join(_plan_writer, 'orchestrator.py')),
        }


_plan_bridge = PlanBridge()


def build_plan(project_dir: str, output_dir: str = None, append_citation_summary: bool = False) -> dict:
    return _plan_bridge.build_plan(project_dir, output_dir, append_citation_summary)


def plan_status() -> dict:
    return _plan_bridge.status()
