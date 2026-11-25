"""Pure validation tests for built-in A/B/C compare. No audio device required."""
import json
from pathlib import Path
import sys
import numpy as np
import soundfile as sf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from mastering_lab.mix_comparison import load_comparison, VARIANT_ORDER


def make_session(tmp_path, bad_variant=None, missing=None):
    versions = {}
    for key in VARIANT_ORDER:
        path = tmp_path / f'{key}.wav'
        if key != missing:
            sr = 48000 if key != bad_variant else 44100
            sf.write(path, np.zeros((4800,2),dtype=np.float32), sr, subtype='PCM_24')
        versions[key] = {'wav':str(path)}
    report = tmp_path / 'comparison.json'
    report.write_text(json.dumps({'status':'ok','variants': versions}),encoding='utf-8')
    return report


def test_all_three_order_and_duration(tmp_path):
    paths, (sr,channels,frames) = load_comparison(make_session(tmp_path))
    assert list(paths) == list(VARIANT_ORDER)
    assert (sr,channels,frames) == (48000,2,4800)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError,match='WAV introuvable'):
        load_comparison(make_session(tmp_path,missing='punchy'))


def test_mismatched_samplerate(tmp_path):
    with pytest.raises(ValueError,match='comparaison synchronisée impossible'):
        load_comparison(make_session(tmp_path,bad_variant='vocal-focus'))


def test_invalid_report(tmp_path):
    with pytest.raises(ValueError,match='Rapport Auto Mix invalide'):
        load_comparison({'status':'error','error':'oops'})


def test_missing_variant(tmp_path):
    report={'status':'ok','variants':{'balanced':{'wav':'irrelevant.wav'}}}
    with pytest.raises((ValueError,FileNotFoundError)):
        load_comparison(report)
