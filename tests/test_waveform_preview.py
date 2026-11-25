import ast
from pathlib import Path
import numpy as np
import soundfile as sf

# Test the extraction logic without requiring the Windows/Qt UI backend.
module_path = Path(__file__).parents[1] / 'src/mastering_lab/waveform_preview.py'
tree = ast.parse(module_path.read_text(encoding='utf-8'))
f = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'waveform_envelope')
namespace = {'Path': Path, 'np': np, 'sf': sf}
exec(compile(ast.Module(body=[f], type_ignores=[]), str(module_path), 'exec'), namespace)
waveform_envelope = namespace['waveform_envelope']


def test_amplitudes_preserve_comparability(tmp_path):
    x = np.zeros((48000, 2), dtype='float32')
    x[12345] = [0.95, -0.83]
    sf.write(tmp_path / 'a.wav', x, 48000, subtype='FLOAT')
    env = waveform_envelope(tmp_path / 'a.wav', max_points=100)
    assert len(env) == 100
    assert np.isclose(np.max(env[:, 1]), 0.95)
    assert np.isclose(np.min(env[:, 0]), -0.83)
    sf.write(tmp_path / 'b.wav', x / 2, 48000, subtype='FLOAT')
    half = waveform_envelope(tmp_path / 'b.wav', max_points=100)
    assert np.isclose(np.max(half[:, 1]), 0.475)


def test_cancellation_and_empty(tmp_path):
    sf.write(tmp_path / 'silent.wav', np.zeros((1000, 1), dtype='float32'), 48000)
    assert waveform_envelope(tmp_path / 'silent.wav', cancelled=lambda: True) is None
    assert waveform_envelope(tmp_path / 'silent.wav', max_points=20).shape == (20, 2)


def test_ui_wiring():
    s = (Path(__file__).parents[1] / 'src/mastering_lab/auto_studio_ui.py').read_text(encoding='utf-8')
    for needle in ['_load_waveforms(paths)', '_waveform_seek', 'clickedPosition.connect', 'card.waveform.setPosition', '_invalidate_waveforms()', '_load_waveforms(player.paths)']:
        assert needle in s
