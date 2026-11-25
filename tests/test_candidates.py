from pathlib import Path
import numpy as np
import soundfile as sf
import pytest
from mastering_lab.reference import analyze
from mastering_lab.candidates import TILTS, plan_candidates, shape_distance, measure_candidate

def make_wav(path, hz=1000, amp=.08):
    sr=48000
    t=np.arange(sr,dtype=float)/sr
    wave=np.sin(2*np.pi*hz*t)*amp
    sf.write(path,np.column_stack([wave,wave]),sr)

def test_profiles_deterministic_and_bounded(tmp_path):
    a,b=tmp_path/'a.wav',tmp_path/'b.wav'
    make_wav(a,1000);make_wav(b,2000)
    plans=plan_candidates(analyze(a),analyze(b))
    assert set(plans)=={'balanced','warm','punchy'}
    assert all(-2<=s['recommended_gain_db']<=2 for v in plans.values() for s in v)
    assert len({tuple(s['recommended_gain_db'] for s in v) for v in plans.values()})>1

def test_identical_original_shape_distance(tmp_path):
    a=tmp_path/'a.wav';make_wav(a)
    assert shape_distance(analyze(a),analyze(a))==0

def test_candidate_qc(tmp_path):
    a,b=tmp_path/'a.wav',tmp_path/'b.wav'
    make_wav(a,amp=.08);make_wav(b,amp=.16)
    out=measure_candidate(b,analyze(a),analyze(a))
    assert out['rms_change_db']>5.5
    assert any('level-match' in v for v in out['warnings'])

def test_bad_strength(tmp_path):
    a=tmp_path/'a.wav';make_wav(a)
    with pytest.raises(ValueError):plan_candidates(analyze(a),analyze(a),strength=0)
