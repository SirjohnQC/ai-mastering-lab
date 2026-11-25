from pathlib import Path
import sys
import json
import numpy as np
import soundfile as sf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.mix_evaluator import analyze_wav, evaluate_comparison, local_hermes_evaluation


def make_fixture(tmp_path, scale=0.3):
    sr=16000
    t=np.arange(sr)/sr
    paths={}
    for key,amp in [('balanced',scale),('vocal-focus',scale*1.1),('punchy',scale*0.9)]:
        x=np.column_stack((amp*np.sin(2*np.pi*250*t),amp*np.sin(2*np.pi*250*t))).astype('float32')
        path=tmp_path/f'{key}.wav'
        sf.write(path,x,sr,subtype='FLOAT')
        paths[key]={'wav':str(path)}
    report={'status':'ok','variants':paths}
    p=tmp_path/'comparison.json';p.write_text(json.dumps(report))
    return p


def test_analyze_peak_rms_and_correlation(tmp_path):
    p=make_fixture(tmp_path)
    m=analyze_wav(tmp_path/'balanced.wav')
    assert m['sample_rate']==16000
    assert m['clipped_samples']==0
    assert 0.99 <= m['stereo_correlation'] <= 1
    assert abs(m['crest_db']-3.01)<0.03
    assert abs(m['sample_peak_dbfs']-20*np.log10(.3))<0.03


def test_relative_analysis(tmp_path):
    evaluation=evaluate_comparison(make_fixture(tmp_path))
    assert evaluation['differences']['balanced']['rms_delta_db']==0
    assert evaluation['differences']['vocal-focus']['rms_delta_db']>0
    assert evaluation['differences']['punchy']['rms_delta_db']<0


def test_local_ai_no_paths_or_audio_and_safe_json(tmp_path):
    evaluation=evaluate_comparison(make_fixture(tmp_path))
    def fake(url,body,seconds):
        assert url=='http://127.0.0.1:11434/api/chat'
        assert body['model']=='hermes3:8b'
        assert 'wav' not in json.loads(body['messages'][1]['content'])
        assert str(tmp_path) not in json.dumps(body)
        return {'message':{'content':'{"summary":"Des niveaux différents", "observations":["aucun avis sonore"], "recommendation":"Écouter à niveau égal", "caveats":["Pas de LUFS"]}'}}
    result=local_hermes_evaluation(evaluation,transport=fake)
    assert result['recommendation']=='Écouter à niveau égal'


def test_network_restricted_to_loopback(tmp_path):
    evaluation=evaluate_comparison(make_fixture(tmp_path))
    with pytest.raises(Exception,match='local'):
        local_hermes_evaluation(evaluation,base_url='https://remote.example.com')


def test_invalid_comparison(tmp_path):
    with pytest.raises(ValueError):
        evaluate_comparison({'status':'error','variants':{}})


def test_corrupt_audio_nonfinite_rejected(tmp_path):
    sr=8000
    x=np.zeros((512,2),dtype='float32')
    x[10,0]=np.nan
    p=tmp_path/'bad.wav';sf.write(p,x,sr,subtype='FLOAT')
    with pytest.raises(ValueError,match='non finis'):
        analyze_wav(p)
