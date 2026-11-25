import math
from pathlib import Path
import numpy as np
import soundfile as sf
import pytest
from mastering_lab.album_ai_brain import (validate_plan, choose_configs, measure_stems,
                                           apply_plan, VARIANTS, GROUPS)
from mastering_lab.album_stem_pipeline import PIPELINE_ID, can_reuse_master


def plan():
    return {'variants': {
        'balanced': {k: 0.0 for k in GROUPS},
        'vocal-focus': {**{k: -0.2 for k in GROUPS}, 'vocals': 0.8},
        'punchy': {**{k: -0.2 for k in GROUPS}, 'drums':0.7, 'bass':0.6},
    }}


def test_validation_accepts_safe_plan():
    assert validate_plan(plan())['vocal-focus']['vocals'] == .8


@pytest.mark.parametrize('value', [4.0, float('nan'), float('inf'), '0.4', True])
def test_validation_rejects_bad_gain(value):
    data = plan()
    data['variants']['balanced']['vocals'] = value
    with pytest.raises(ValueError): validate_plan(data)


def test_validation_rejects_wrong_group_or_hallucinated_field():
    data=plan();data['variants']['balanced']['eq_hz'] = 300
    with pytest.raises(ValueError): validate_plan(data)


def test_validation_rejects_nonfocus_variants():
    data=plan();data['variants']['vocal-focus']['vocals']=-.9
    with pytest.raises(ValueError): validate_plan(data)


def test_safe_fallback_no_ollama():
    config={'tracks':[{'file':'Vocals.wav','gain_db':0}, {'file':'Drums.wav','gain_db':0}]}
    configs, report=choose_configs(config, ask_fn=lambda m: (_ for _ in ()).throw(TimeoutError('off')),
                                   analyzer=lambda c: [])
    assert report['mode']=='fallback'
    assert configs['vocal-focus']['tracks'][0]['gain_db'] == 1.0


def test_ai_applied_no_mutation():
    config={'tracks':[{'file':'Vocals.wav','gain_db':0}, {'file':'Drums.wav','gain_db':0}]}
    variants, report=choose_configs(config, analyzer=lambda c: [], ask_fn=lambda m: plan())
    assert report['mode']=='hermes'
    assert variants['vocal-focus']['tracks'][0]['gain_db']==0.8
    assert config['tracks'][0]['gain_db']==0


def test_real_wav_analysis(tmp_path):
    rate=16000; t=np.arange(rate*2)/rate
    stems=[]
    for name,freq in [('Vocals.wav',330),('Drums.wav',100)]:
        path=tmp_path/name;sf.write(path, .1*np.sin(t*freq*2*np.pi), rate)
        stems.append({'file':str(path)})
    result=measure_stems({'tracks':stems})
    assert len(result)==2 and result[0]['group']=='vocals'
    assert -26 < result[0]['sampled_rms_dbfs'] < -20
    assert math.isfinite(result[1]['sampled_centroid_hz'])


def test_old_cache_rejected(tmp_path):
    source=tmp_path/'stem';source.mkdir()
    for n in ('Vocals.wav','Drums.wav'):(source/n).write_bytes(b'raw')
    output=tmp_path/'master.wav';output.write_bytes(b'output')
    from mastering_lab.album_stem_pipeline import source_signature
    row={'kind':'stems','path':str(source),'status':'qc_pass','result':{'status':'qc_pass','file':str(output),
          'album_source_signature':source_signature(source,'stems'), 'album_pipeline':'album_three_dry_variants_v1'}}
    assert not can_reuse_master(row)
    assert 'hermes' in PIPELINE_ID
