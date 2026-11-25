import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pytest
from mastering_lab.ai_review import review_proposals,merge_review,AIReviewError

PROPOSALS=[{'index':0,'name':'vocals','category':'vocals','file':'C:/private/stems/myfile.wav','metrics':{'rms_dbfs':-23.1,'high_share':0.4},'warnings':[], 'fx_chain':[{'role':'corrective_eq','plugin':'C:/FabFilter.vst3','enabled':False},{'role':'resonance','plugin':'C:/soothe.vst3','enabled':False}], 'reasons':[]}]

def test_local_review_sanitizes_private_paths():
    def fake(url, body, timeout):
        assert url == 'http://127.0.0.1:11434/api/chat'
        assert 'myfile.wav' not in str(body) and 'FabFilter.vst3' not in str(body)
        return {'message':{'content':'{"reviews":[{"index":0,"roles":[{"role":"resonance","decision":"omit","reason":"Pas assez de preuve"},{"role":"limiter","decision":"keep"}],"note":"Prudence"}]}'}}
    result=review_proposals(PROPOSALS,transport=fake)
    assert result[0]['roles']==[{'role':'resonance','decision':'omit','reason':'Pas assez de preuve'}]
    merged=merge_review(PROPOSALS,result)
    assert len(merged[0]['fx_chain'])==1
    assert len(PROPOSALS[0]['fx_chain'])==2
    assert merged[0]['fx_chain'][0]['enabled'] is False

def test_no_external_endpoints():
    with pytest.raises(AIReviewError):review_proposals(PROPOSALS,base_url='https://example.com')

def test_bad_response_fails_closed():
    with pytest.raises(AIReviewError):review_proposals(PROPOSALS,transport=lambda *args:{'message':{'content':'not json'}})

def test_unreviewed_steps_remain_bypassed():
    r=merge_review(PROPOSALS,[{'index':0,'roles':[],'note':'test'}])
    assert len(r[0]['fx_chain'])==2
    assert all(not x['enabled'] for x in r[0]['fx_chain'])
