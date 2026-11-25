from pathlib import Path
import sys
import json
import numpy as np
import soundfile as sf
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mastering_lab.fx_chain import validate_chain, chain_fingerprint, prepare_chain

def test_plugin_chain_validation_and_order(tmp_path):
    a=tmp_path/'A.vst3'; b=tmp_path/'B.vst3';a.write_bytes(b'a');b.write_bytes(b'b')
    chain=[{'role':'corrective_eq','plugin':str(a),'enabled':True},{'role':'compression','plugin':str(b),'enabled':False}]
    assert [x['role'] for x in validate_chain(chain)]==['corrective_eq','compression']
    assert validate_chain(chain)[1]['enabled'] is False

def test_invalid_plugin_rejected(tmp_path):
    with pytest.raises(ValueError):validate_chain([{'role':'reverb','plugin':str(tmp_path/'missing.vst3')}])
    with pytest.raises(ValueError):validate_chain([{'role':'mystery','plugin':str(tmp_path/'yes.vst3')}])

def test_cache_changes_on_source_and_chain(tmp_path):
    wav=tmp_path/'stem.wav';wav.write_bytes(b'hello')
    vst=tmp_path/'eq.vst3';vst.write_bytes(b'1')
    chain=[{'role':'corrective_eq','plugin':str(vst)}]
    a=chain_fingerprint(wav,chain)
    assert a==chain_fingerprint(wav,chain)
    chain[0]['enabled']=False
    assert a!=chain_fingerprint(wav,chain)

def test_sequential_render_with_mock_host(tmp_path, monkeypatch):
    wav=tmp_path/'stem.wav';sf.write(wav,np.zeros((480,2),dtype=np.float32),48000,subtype='PCM_24')
    host=tmp_path/'host.exe';host.write_bytes(b'fake')
    vst=tmp_path/'eq.vst3';vst.write_bytes(b'fake')
    calls=[]
    import mastering_lab.host as bridge
    def mock_run(exe,command,**kwargs):
        calls.append(command)
        if command=='inspect':return {'latency_samples':0}
        import shutil
        shutil.copyfile(kwargs['input_file'],kwargs['output_file'])
        return {'status':'ok','latency_samples':0,'tail_samples':0}
    monkeypatch.setattr(bridge,'run_host',mock_run)
    result=prepare_chain(wav,[{'role':'corrective_eq','plugin':str(vst)}],tmp_path/'out.wav',host)
    assert result['status']=='ok' and (tmp_path/'out.wav').is_file()
    assert calls==['inspect','render']

def test_reported_latency_is_compensated_by_native_host(tmp_path, monkeypatch):
    wav=tmp_path/'stem.wav';sf.write(wav,np.zeros((480,2)),48000)
    vst=tmp_path/'eq.vst3';vst.write_bytes(b'fake')
    host=tmp_path/'host.exe';host.write_bytes(b'fake')
    import mastering_lab.host as bridge
    def fake_host(exe, command, **kwargs):
        if command == 'inspect': return {'latency_samples':64}
        import shutil
        shutil.copyfile(kwargs['input_file'],kwargs['output_file'])
        return {'status':'ok','latency_samples':64,'tail_samples':0}
    monkeypatch.setattr(bridge,'run_host',fake_host)
    result=prepare_chain(wav,[{'role':'corrective_eq','plugin':str(vst)}],tmp_path/'out.wav',host)
    assert result['stages'][0]['latency_compensated_samples']==64


def test_reverb_tail_is_rejected(tmp_path,monkeypatch):
    wav=tmp_path/'stem.wav';sf.write(wav,np.zeros((480,2)),48000)
    vst=tmp_path/'rev.vst3';vst.write_bytes(b'fake')
    host=tmp_path/'host.exe';host.write_bytes(b'fake')
    import mastering_lab.host as bridge
    def fake_host(exe,command,**kwargs):
        if command=='inspect':return {'latency_samples':0}
        import shutil
        shutil.copyfile(kwargs['input_file'],kwargs['output_file'])
        return {'status':'ok','latency_samples':0,'tail_samples':2400}
    monkeypatch.setattr(bridge,'run_host',fake_host)
    with pytest.raises(ValueError,match='tail'):
        prepare_chain(wav,[{'role':'reverb','plugin':str(vst)}],tmp_path/'out.wav',host)
    assert not (tmp_path/'out.wav').exists()
