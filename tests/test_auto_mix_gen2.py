from pathlib import Path
import json
import sys
import numpy as np
import soundfile as sf
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from mastering_lab.auto_mix_gen2 import (validate_deltas, deterministic_proposal,
                                         model_proposal, build_configs, render_generation, read_session)


def test_bounds_and_missing_groups():
    good=deterministic_proposal()['deltas']
    assert validate_deltas(good)==good
    good['punchy']['vocals']=1.1
    with pytest.raises(ValueError,match='±1'):validate_deltas(good)
    good['punchy']['vocals']=0
    good['balanced']['bass']=0.1
    with pytest.raises(ValueError,match='Balanced'):validate_deltas(good)


def test_hermes_json_only_and_rejects_excessive():
    def fake(url, body, timeout):
        assert url.endswith('/api/chat')
        assert body['model']=='hermes3:8b'
        return {'message': {'content': json.dumps({'deltas': deterministic_proposal()['deltas'], 'reason': 'test'})}}
    result=model_proposal({'metrics':{}},transport=fake)
    assert result['source']=='hermes'
    def malicious(url,body,timeout):
        data=deterministic_proposal()['deltas']
        data['vocal-focus']['vocals']=12
        return {'message': {'content': json.dumps({'deltas':data})}}
    with pytest.raises(ValueError):model_proposal({'metrics':{}},transport=malicious)


def test_build_keeps_original_and_fx_state():
    cfg={'tracks':[{'file':'Lead Vocals.wav','gain_db':0,'fx_chain':[{'enabled':True,'plugin':'proq'}]},
                   {'file':'Drums.wav','gain_db':-3,'mute':True}]}
    output=build_configs(cfg,deterministic_proposal()['deltas'])
    assert output['vocal-focus']['tracks'][0]['gain_db']==0.8
    assert output['vocal-focus']['tracks'][0]['fx_chain']==cfg['tracks'][0]['fx_chain']
    assert output['punchy']['tracks'][1]['gain_db']==-3
    assert cfg['tracks'][0]['gain_db']==0


def test_render_pipeline_three_wavs(tmp_path):
    folder=tmp_path/'stems'; folder.mkdir()
    cfg=tmp_path/'stem-mix.json'
    cfg.write_text(json.dumps({'tracks':[{'file':str(folder/'Lead Vocals.wav'),'gain_db':0}]}))
    prepared=tmp_path/'prepared.json'; prepared.write_text('{}')
    session=tmp_path/'session-a'; session.mkdir()
    report=session/'comparison.json'
    report.write_text(json.dumps({'status':'ok', 'source':{'folder':str(folder),'config':str(cfg),'prepared':str(prepared)}}))
    root=tmp_path/'root'; (root/'scripts').mkdir(parents=True); (root/'scripts'/'stem_mix.py').write_text('# test only')
    def runner(cmd,**kwargs):
        output=Path(cmd[cmd.index('--output')+1])
        data=np.zeros((200,2), dtype='float32')
        sf.write(output,data,48000,subtype='FLOAT')
        return type('Result',(),{'returncode':0, 'stdout':'', 'stderr':''})()
    result=render_generation(report,deterministic_proposal(),project_root=root,runner=runner)
    saved=json.loads(Path(result['comparison']).read_text())
    assert saved['generation']==2
    assert set(saved['variants'])=={'balanced','vocal-focus','punchy'}
    assert Path(saved['parent_comparison'])==report.resolve()
    assert cfg.is_file() and prepared.read_text()=='{}'
    third=render_generation(result['comparison'],deterministic_proposal(),project_root=root,runner=runner)
    third_saved=json.loads(Path(third['comparison']).read_text())
    assert third_saved['generation']==3
    assert third_saved['parent_comparison']==result['comparison']
    assert third['folder'] != result['folder']


def test_old_session_explains_upgrade(tmp_path):
    report=tmp_path/'comparison.json';report.write_text('{"status":"ok","variants":{}}')
    with pytest.raises(ValueError,match='Regénère'):read_session(report)
