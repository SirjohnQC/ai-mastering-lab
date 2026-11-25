import sys
from pathlib import Path
import numpy as np
import soundfile as sf
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.loudness_match import matching_gains, match_files, measure_lufs


def test_matching_never_boosts():
    data = {'balanced': {'lufs_i': -15}, 'vocal-focus': {'lufs_i': -12}, 'punchy': {'lufs_i': -17}}
    gains = matching_gains(data)
    assert gains['punchy'] == 1
    assert abs(20 * np.log10(gains['balanced']) - (-2)) < 1e-7
    assert abs(20 * np.log10(gains['vocal-focus']) - (-5)) < 1e-7


def test_large_difference_rejected():
    with pytest.raises(ValueError, match='Écart LUFS'):
        matching_gains({'a':{'lufs_i': -10}, 'b':{'lufs_i': -15}, 'c':{'lufs_i': -40}})


def test_real_wav_measurement_and_matching(tmp_path):
    rate = 48000
    n = 2 * rate
    t = np.arange(n) / rate
    base = (np.sin(2*np.pi*430*t) + 0.25*np.sin(2*np.pi*1720*t)).astype('float32')
    paths = {}
    for name, amp in [('balanced', .13), ('vocal-focus', .19), ('punchy', .08)]:
        path = tmp_path / f'{name}.wav'
        sf.write(path, np.column_stack((base*amp, base*amp)), rate, subtype='FLOAT')
        paths[name] = path
    before = {k: v.read_bytes() for k,v in paths.items()}
    result = match_files(paths)
    for k in paths:
        assert result['gains'][k] <= 1.0000001
        assert before[k] == paths[k].read_bytes()
    values = [result['measurements'][k]['lufs_i'] + 20*np.log10(result['gains'][k]) for k in paths]
    assert max(values)-min(values) < .02


def test_silence_rejected(tmp_path):
    file = tmp_path/'silent.wav'
    sf.write(file, np.zeros((48000,2), dtype='float32'), 48000)
    with pytest.raises(ValueError, match='Silence'):
        measure_lufs(file)
