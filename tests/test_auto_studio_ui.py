from pathlib import Path
import ast
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src' / 'mastering_lab'
sys.path.insert(0, str(ROOT / 'src'))


def test_python_files_parse():
    for name in ['auto_studio_ui.py', 'desktop.py', 'stem_plus_ui.py', 'version.py']:
        ast.parse((SOURCE / name).read_text(encoding='utf-8'))


def test_old_stem_mixer_emits_file_and_pipeline_signals():
    text = (SOURCE / 'stem_plus_ui.py').read_text(encoding='utf-8')
    for key in ('audioLoaded = Signal', 'productionStatus = Signal', 'productionFinished = Signal',
                'self.audioLoaded.emit', 'self.productionStatus.emit', 'self.productionFinished.emit'):
        assert key in text
    assert 'guided_frontend' in text


def test_dashboard_is_first_tab_and_mastering_is_reachable():
    text = (SOURCE / 'desktop.py').read_text(encoding='utf-8')
    assert "self.workspace.insertTab(0, self.auto_studio, 'AUTO STUDIO')" in text
    assert 'self.auto_studio.openMastering.connect(self.accept_auto_studio_mix)' in text
    assert 'self.workspace.setCurrentIndex(self.workspace.indexOf(self._mastering_page))' in text


def test_results_provide_selection_playback_and_actual_handoff():
    text = (SOURCE / 'auto_studio_ui.py').read_text(encoding='utf-8')
    for key in ('Balanced', 'Vocal Focus', 'Punchy', '_toggle_play', '_continue_mastering',
                'shutil.copy2', 'openMastering.emit', 'start_automatic_analysis'):
        assert key in text
    assert 'self.continue_btn = QPushButton' in text


def test_no_fake_album_or_streaming_master():
    text = (SOURCE / 'auto_studio_ui.py').read_text(encoding='utf-8')
    assert 'pas encore des masters certifiés' in text
    translations = (SOURCE / 'ui_language.py').read_text(encoding='utf-8')
    assert 'For multiple songs or a stereo WAV, open Album Mode.' in translations
    assert 'albums complets suivront' not in translations


def test_real_comparison_report_validation(tmp_path):
    import soundfile as sf
    import numpy as np
    from mastering_lab.mix_comparison import load_comparison
    import math
    wav = np.zeros((480, 2), dtype='float32')
    variants = {}
    for name in ('balanced', 'vocal-focus', 'punchy'):
        dest = tmp_path / f'{name}.wav'
        sf.write(dest, wav, 48000)
        variants[name] = {'wav': str(dest)}
    report = tmp_path / 'comparison.json'
    report.write_text(json.dumps({'status': 'ok', 'variants': variants}), encoding='utf-8')
    paths, meta = load_comparison(report)
    assert tuple(paths) == ('balanced', 'vocal-focus', 'punchy')
    assert meta == (48000, 2, 480)
