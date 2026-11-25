import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pytest
from mastering_lab.fx_bulk_apply import apply_proposals

def test_apply_all_enabled_preserves_existing():
    tracks=[{'file':'a.wav','fx_chain':[{'role':'reverb','plugin':'r.vst3','enabled':False}]},{'file':'b.wav','fx_chain':[]}]
    proposals=[{'index':0,'file':'a.wav','fx_chain':[{'role':'eq','plugin':'eq.vst3','enabled':False}]},
               {'index':1,'file':'b.wav','fx_chain':[{'role':'compression','plugin':'c.vst3','enabled':False}]}]
    report=apply_proposals(tracks,proposals,enable_new=True)
    assert report['added']==2
    assert tracks[0]['fx_chain'][0]['enabled'] is False
    assert tracks[0]['fx_chain'][1]['enabled'] is True
    assert tracks[1]['fx_chain'][0]['enabled'] is True
    assert all(x['auto_fx_suggestion'] for t in tracks for x in t['fx_chain'] if x.get('auto_fx_suggestion'))

def test_bypass_and_deduplicate():
    track=[{'file':'a.wav','fx_chain':[]}]
    p=[{'index':0,'file':'a.wav','fx_chain':[{'role':'eq','plugin':'eq.vst3'}]}]
    assert apply_proposals(track,p,enable_new=False)['added']==1
    assert track[0]['fx_chain'][0]['enabled'] is False
    assert apply_proposals(track,p,enable_new=True)['added']==0
    assert track[0]['fx_chain'][0]['enabled'] is False

def test_changed_stem_refused_without_mutation():
    tracks=[{'file':'a.wav','fx_chain':[]}]
    with pytest.raises(ValueError):apply_proposals(tracks,[{'index':0,'file':'different.wav','fx_chain':[{'role':'eq','plugin':'eq.vst3'}]}],enable_new=True)
    assert tracks[0]['fx_chain']==[]

def test_invalid_second_proposal_is_atomic():
    tracks=[{'file':'a.wav','fx_chain':[]},{'file':'b.wav','fx_chain':[]}]
    proposals=[{'index':0,'file':'a.wav','fx_chain':[{'role':'eq','plugin':'eq.vst3'}]}, {'index':1,'file':'bad.wav','fx_chain':[]}]
    with pytest.raises(ValueError):apply_proposals(tracks,proposals,enable_new=True)
    assert tracks[0]['fx_chain']==[]
