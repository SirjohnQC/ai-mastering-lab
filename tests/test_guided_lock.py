"""Structural regression checks without requiring PySide6 on CI."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab' / 'stem_plus_ui.py'
TREE = ast.parse(SRC.read_text(encoding='utf-8'))
PAGE = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'StemPlusPage')
METHODS = {n.name: n for n in PAGE.body if isinstance(n, ast.FunctionDef)}

def source(name):
    return ast.get_source_segment(SRC.read_text(encoding='utf-8'), METHODS[name])

def test_modal_processing_dialog():
    s=source('_show_guided_progress')
    assert 'Qt.ApplicationModal' in s and 'QProgressDialog' in s and "'Annuler'" in s

def test_cancel_stops_subprocess_and_ignores_ollama():
    assert 'self.job.kill()' in source('_cancel_guided_production')
    assert 'if self._guided_cancelled:' in source('_on_ai_review_finished')
    assert 'if self._guided_cancelled:' in source('job_done')

def test_progress_closed_on_completion_and_approval():
    assert 'self._hide_guided_progress()' in source('_stop_guided_production')
    assert 'self._hide_guided_progress()' in source('_show_fx_proposals')
    assert 'self._hide_guided_progress()' in source('job_done')

def test_prevents_queued_start_after_cancel():
    assert 'if self._guided_pipeline else None' in source('start_guided_production')
