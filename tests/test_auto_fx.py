import sys
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mastering_lab.auto_fx import analyze_stem, suggest_chain, suggest_project, gentle_eq_moves

def test_audio_measurement(tmp_path):
    sr=48000
    t=np.arange(sr,dtype=np.float64)/sr
    x=.1*np.sin(2*np.pi*350*t)
    path=tmp_path/'vocals.wav'
    sf.write(path,x,sr)
    features=analyze_stem(path)
    assert features['duration_s']==1
    assert -25<features['rms_dbfs']<-20
    assert features['low_mid_share'] > .5
    assert gentle_eq_moves(features)[0]['recommended_gain_db']==-.7

def test_roles_and_safe_bypass(tmp_path):
    eq=tmp_path/'FabFilter Pro-Q 4.vst3';eq.write_text('dummy')
    comp=tmp_path/'comp.vst3';comp.write_text('dummy')
    result=suggest_chain('vocals',{'level_variation_db':12,'crest_db':10,'presence_share':.1},
                         {'corrective_eq':str(eq),'compression':str(comp)})
    assert [s['role'] for s in result['fx_chain']]==['corrective_eq','compression']
    assert all(not s['enabled'] for s in result['fx_chain'])
    assert result['review_required'] is True

def test_no_unowned_plugins(tmp_path):
    result=suggest_chain('drums',{'crest_db':19},{'compression':str(tmp_path/'missing.vst3')})
    assert result['fx_chain']==[]

def test_project(tmp_path):
    path=tmp_path/'2 Drums.wav';sf.write(path,np.zeros((4096,2)),48000)
    proposals=suggest_project([{'file':str(path),'category':'drums'}],{})
    assert proposals[0]['name']=='2 Drums'
    assert proposals[0]['fx_chain']==[]
