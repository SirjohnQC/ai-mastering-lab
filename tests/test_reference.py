import numpy as np
import pytest
import soundfile as sf
from mastering_lab.reference import analyze,suggest,report
from mastering_lab.proq4 import build_changes,frequency_normalized,gain_normalized

def tone(path,frequency):
    sr=48000;ts=np.arange(sr)/sr
    x=np.sin(2*np.pi*frequency*ts)*.1
    sf.write(path,np.column_stack((x,x)),sr)

def test_identical_reference_gives_zero(tmp_path):
    x=tmp_path/'a.wav';tone(x,1000)
    data=report(x,x)
    assert all(abs(p['recommended_gain_db'])<.01 for p in data['suggestions'])

def test_wave_stats(tmp_path):
    x=tmp_path/'a.wav';tone(x,1000)
    p=analyze(x)
    assert p.sample_rate==48000 and p.duration_seconds==1
    assert -25 < p.rms_dbfs < -20

def test_proq4_frequency_mapping():
    assert frequency_normalized(1000)==pytest.approx(.575188457965851,abs=2e-6)
    assert gain_normalized(6)==pytest.approx(.6)

def test_build_changes_matches_actual_parameter_names():
    names=['Band 1 Used','Band 1 Enabled','Band 1 Frequency','Band 1 Gain']
    params=[dict(index=i,name=n,automatable=True,text='Unused' if i==0 else '-') for i,n in enumerate(names)]
    actions=build_changes({'name':'FabFilter Pro-Q 4','parameters':params},[dict(center_hz=1000,recommended_gain_db=3.)])
    assert [i for i,v in actions]==[0,1,2,3]
    assert actions[0][1]==1
    assert actions[-1][1]==pytest.approx(.55)

def test_reject_invalid_strength(tmp_path):
    x=tmp_path/'a.wav';tone(x,1000)
    with pytest.raises(ValueError):report(x,x,strength=0)
