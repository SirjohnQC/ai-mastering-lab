from pathlib import Path
import ast
root=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'
ui=(root/'stem_plus_ui.py').read_text(encoding='utf-8')
compare=(root/'mix_compare_ui.py').read_text(encoding='utf-8')
version=(root/'version.py').read_text(encoding='utf-8')

def test_syntax():
    for f in root.glob('*.py'): ast.parse(f.read_text(encoding='utf-8'))

def test_comparator_not_blocking():
    body=ui.split('    def open_auto_mix_comparison(',1)[1].split('    def auto_mix_candidates(',1)[0]
    assert 'player.show()' in body
    assert 'player.exec()' not in body
    assert 'self._compare_window = player' in body

def test_renderer_busy_stopped_before_comparator():
    body=ui.split("elif self._kind == 'auto_mix':",1)[1].split("elif self._kind == 'send':",1)[0]
    assert body.index('self._set_busy(False)') < body.index('self.open_auto_mix_comparison(')
    assert 'QTimer.singleShot' in body

def test_auto_analysis_emits_completion_after_lufs():
    assert 'automaticAnalysisFinished = Signal(bool, str)' in compare
    assert 'self.automaticAnalysisFinished.emit(True,' in compare
    assert 'self.automaticAnalysisFinished.emit(False,' in compare
    assert 'self._auto_loudness_pending = True' in compare
    assert 'player.automaticAnalysisFinished.connect(self._on_auto_analysis_finished)' in ui

def test_title_updated():
    assert "APP_VERSION = '0.11.8'" in version
