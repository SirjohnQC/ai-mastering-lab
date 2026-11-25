"""Regression checks for the v0.11.1 nested-dialog fix.

Qt GUI/audio-device integration must still be verified on Windows.
"""
import ast
import json
from pathlib import Path
import sys
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'src'))
from mastering_lab.mix_comparison import load_comparison

UI = HERE / 'src' / 'mastering_lab' / 'mix_compare_ui.py'


def _method(name):
    tree = ast.parse(UI.read_text(encoding='utf-8'))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'MixCompareDialog')
    return next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == name)


def test_gen2_does_not_open_nested_dialog():
    method = _method('_open_gen2_comparison')
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'MixCompareDialog'
                   for n in ast.walk(method))
    assert any(isinstance(n, ast.Attribute) and n.attr == '_load_comparison_in_place'
               for n in ast.walk(method))


def test_switch_closes_files_and_resets_generation_state():
    s = ast.get_source_segment(UI.read_text(encoding='utf-8'), _method('_load_comparison_in_place'))
    for fragment in ('load_comparison(report_path)', 'stream.stop()', 'old.close()',
                     'self._playing = False', 'self._loudness_matched = False',
                     'self._analysis_text.clear()', 'self._refresh_generation_label()'):
        assert fragment in s


def test_comparison_gen1_gen2_audio_files_validate(tmp_path):
    paths = {}
    for gen in (1, 2):
        folder = tmp_path / f'gen{gen}'
        folder.mkdir()
        for key in ('balanced', 'vocal-focus', 'punchy'):
            wav = folder / f'{key}.wav'
            sf.write(wav, np.zeros((800, 2), dtype='float32'), 48000)
        doc = {'status': 'ok', 'variants': {k: {'wav': f'{k}.wav'} for k in
             ('balanced', 'vocal-focus', 'punchy')}}
        if gen == 2:
            doc['generation'] = 2
            doc['parent_comparison'] = str(tmp_path / 'gen1' / 'comparison.json')
        report = folder / 'comparison.json'
        report.write_text(json.dumps(doc), encoding='utf-8')
        paths[gen] = report
    for gen in (1, 2):
        wavs, spec = load_comparison(paths[gen])
        assert len(wavs) == 3 and spec == (48000, 2, 800)
    assert json.loads(paths[2].read_text())['parent_comparison'] == str(paths[1])
