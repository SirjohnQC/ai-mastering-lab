import sys
from pathlib import Path
import pytest
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mastering_lab.plugin_parameters import parse_parameter_overrides
from mastering_lab.fx_chain import validate_chain, chain_fingerprint, prepare_chain


def test_validation(tmp_path):
    plugin=tmp_path/'some.vst3';plugin.write_bytes(b'ok')
    c=validate_chain([{'role':'corrective_eq','plugin':str(plugin),'parameter_overrides':[{'index':3,'value':0.6}]}])
    assert c[0]['parameter_overrides']==[{'index':3,'value':0.6}]
    assert parse_parameter_overrides([{'index':3,'value':0.6}])==[(3,0.6)]
    for val in ([{'index':3,'value':1.1}],[{'index':True,'value':.5}],[{'index':3,'value':.5},{'index':3,'value':.6}],[{'index':3,'value':float('nan')}],{'3':.2}):
        with pytest.raises(ValueError):parse_parameter_overrides(val)


def test_cache_fingerprint_includes_overrides(tmp_path):
    source=tmp_path/'s.wav';source.write_bytes(b'abc')
    vst=tmp_path/'v.vst3';vst.write_bytes(b'123')
    chain=[{'role':'corrective_eq','plugin':str(vst),'parameter_overrides':[]}]
    old=chain_fingerprint(source,chain)
    chain[0]['parameter_overrides']=[{'index':3,'value':0.6}]
    assert old != chain_fingerprint(source,chain)


def test_overrides_reach_host(tmp_path,monkeypatch):
    src=tmp_path/'input.wav';sf.write(src,np.zeros((512,2)),48000)
    vst=tmp_path/'test.vst3';vst.write_bytes(b'x')
    host=tmp_path/'mastering-host.exe';host.write_bytes(b'x')
    from mastering_lab import host as api
    calls=[]
    def mock_host(exe,cmd,**kwargs):
        calls.append((cmd,kwargs))
        if cmd=='inspect':return {'latency_samples':0}
        import shutil
        shutil.copyfile(kwargs['input_file'],kwargs['output_file'])
        return {'status':'ok','latency_samples':0,'tail_samples':0}
    monkeypatch.setattr(api,'run_host',mock_host)
    prepare_chain(src,[{'role':'corrective_eq','plugin':str(vst),'parameter_overrides':[{'index':0,'value':1.0},{'index':3,'value':0.6}]}],tmp_path/'out.wav',host)
    assert calls[1][1]['parameter_changes']==[(0,1.0),(3,0.6)]
