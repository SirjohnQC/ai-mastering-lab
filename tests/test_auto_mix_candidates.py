import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from mastering_lab.auto_mix_candidates import candidate_configs

def test_three_variants_do_not_modify_source():
    cfg={'tracks':[{'file':'Lead Vocals.wav','gain_db':0.,'mute':False,'fx_chain':[{'plugin':'test'}]},
                   {'file':'Drums.wav','gain_db':0.,'mute':False}]}
    variants=candidate_configs(cfg)
    assert list(variants)==['balanced','vocal-focus','punchy']
    assert variants['vocal-focus']['tracks'][0]['gain_db']==1.
    assert variants['punchy']['tracks'][1]['gain_db']==1.
    assert cfg['tracks'][0]['gain_db']==0.
    assert variants['balanced']['tracks'][0]['fx_chain']==cfg['tracks'][0]['fx_chain']

def test_limits_and_mute_preserved():
    cfg={'tracks':[{'file':'Lead Vocals.wav','gain_db':17.8,'mute':False},
                   {'file':'Drums.wav','gain_db':-2.,'mute':True}]}
    variants=candidate_configs(cfg)
    assert variants['vocal-focus']['tracks'][0]['gain_db']==18.
    assert variants['punchy']['tracks'][1]['gain_db']==-2.
    assert variants['punchy']['tracks'][1]['mute'] is True
