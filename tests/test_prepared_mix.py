"""Run from the installed project's root using pytest."""
from pathlib import Path
import json
import subprocess
import sys
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from mastering_lab.stem_mixer import render_mix


def test_prepared_print_is_actually_used(tmp_path):
    folder=tmp_path/'stems';folder.mkdir()
    original=folder/'Lead Vocals.wav'
    sr=48000
    samples=np.full((1000,2),0.2,dtype=np.float32)
    sf.write(original,samples,sr,subtype='FLOAT')
    wet=tmp_path/'wet.wav'
    sf.write(wet,samples*0.5,sr,subtype='FLOAT')
    config={'tracks':[{'file':str(original),'gain_db':0,'pan':0,'eq':True,'mute':False,
                       'fx_chain':[{'role':'compression','plugin':'dummy','enabled':True}]}]}
    out=tmp_path/'render.wav'
    render_mix(folder,config,out,prepared={'0':str(wet)})
    audio,_=sf.read(out,always_2d=True)
    assert audio.shape == samples.shape
    np.testing.assert_allclose(audio,np.full_like(audio,0.1),atol=1e-6)


def test_cli_accepts_prepared_arg_on_dry_stems(tmp_path):
    folder=tmp_path/'stems';folder.mkdir()
    track=folder/'Drums.wav'
    sf.write(track,np.zeros((256,2),dtype=np.float32),48000)
    config=tmp_path/'mix.json'
    config.write_text(json.dumps({'tracks':[{'file':str(track),'eq':False}]}))
    out=tmp_path/'dry.wav'
    result=subprocess.run([sys.executable,str(ROOT/'scripts'/'stem_mix.py'),'--folder',str(folder),
             '--config',str(config),'--prepared',str(tmp_path/'does-not-exist.json'),
             '--output',str(out)],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert out.exists()
