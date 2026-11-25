from pathlib import Path
import numpy as np
import soundfile as sf
import pytest
from mastering_lab.stem_mixer import config_template, parse_tracks, render_mix, _stereo

def make_stems(d, rate=8000):
    d.mkdir()
    t=np.arange(rate)/rate
    sf.write(d/'vocals.wav',(.1*np.sin(2*np.pi*440*t)).astype('float32'),rate)
    sf.write(d/'guitars.wav',np.column_stack((.05*np.sin(2*np.pi*220*t),.05*np.sin(2*np.pi*220*t))).astype('float32'),rate)

def test_template(tmp_path):
    d=tmp_path/'stems';make_stems(d)
    cfg=config_template(d)
    assert len(cfg['tracks'])==2
    assert not any(t['eq'] for t in cfg['tracks'])

def test_render_and_no_overwrite(tmp_path):
    d=tmp_path/'stems';make_stems(d)
    cfg=config_template(d);out=tmp_path/'mix.wav'
    r=render_mix(d,cfg,out)
    x,sr=sf.read(out)
    assert sr==8000 and x.shape==(8000,2)
    assert abs(x).max()<.25
    assert r['status']=='ok' and out.with_suffix('.mix.json').exists()
    with pytest.raises(ValueError):render_mix(d,cfg,d/'vocals.wav')

def test_peak_safety(tmp_path):
    d=tmp_path/'stems';d.mkdir()
    sf.write(d/'vocals.wav',np.ones(8000,dtype='float32')*.95,8000)
    sf.write(d/'guitars.wav',np.ones(8000,dtype='float32')*.95,8000)
    out=tmp_path/'safe.wav';r=render_mix(d,config_template(d),out)
    x,_=sf.read(out)
    assert np.max(np.abs(x))<=10**(-3/20)+1e-5
    assert r['global_safety_gain_db']<0

def test_misaligned_rejected(tmp_path):
    d=tmp_path/'stems';d.mkdir()
    sf.write(d/'vocals.wav',np.zeros(8000),8000)
    sf.write(d/'guitars.wav',np.zeros(7000),8000)
    with pytest.raises(ValueError,match='duration'):
        render_mix(d,config_template(d),tmp_path/'out.wav')

def test_sample_rate_mismatch(tmp_path):
    d=tmp_path/'stems';d.mkdir()
    sf.write(d/'vocals.wav',np.zeros(8000),8000)
    sf.write(d/'guitars.wav',np.zeros(44100),44100)
    with pytest.raises(ValueError,match='sample rates'):
        render_mix(d,config_template(d),tmp_path/'out.wav')

def test_eq_requires_plugin(tmp_path):
    d=tmp_path/'stems';make_stems(d)
    cfg=config_template(d);cfg['tracks'][0]['eq']=True
    with pytest.raises(ValueError,match='EQ enabled'):
        render_mix(d,cfg,tmp_path/'out.wav')

def test_traversal_rejected(tmp_path):
    d=tmp_path/'stems';make_stems(d)
    cfg=config_template(d)
    cfg['tracks'][0]['file']=str(tmp_path/'other.wav')
    with pytest.raises(ValueError,match='inside'):
        parse_tracks(cfg,d)

def test_center_pan_mono():
    x=np.ones((8,1))
    y=_stereo(x,0,0)
    assert y.shape==(8,2)
    assert np.allclose(y[:,0],y[:,1])
