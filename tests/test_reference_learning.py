import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
import soundfile as sf
from mastering_lab.reference_learning import (extract_features, load_library, save_library,
    add_reference, reference_context, library_path)
from mastering_lab.album_mix_evaluation import choose_candidate
from mastering_lab.album_stem_pipeline import reference_signature


def tone(path, frequency=220, amplitude=.15):
    t=np.arange(48000*2)/48000
    data=np.column_stack((np.sin(2*np.pi*frequency*t),np.sin(2*np.pi*frequency*t)))*amplitude
    sf.write(path,data,48000)
    return str(path)


def test_profile_distinguishes_spectral_reference(tmp_path):
    low=extract_features(tone(tmp_path/'low.wav',100))
    high=extract_features(tone(tmp_path/'high.wav',6000))
    assert sum(low['spectral_shares']) == __import__('pytest').approx(1,abs=1e-4)
    assert low['spectral_shares'][1] > high['spectral_shares'][1]
    assert high['spectral_shares'][6] > low['spectral_shares'][6]
    assert low['sample_rate']==48000


def test_library_roundtrip_and_selection(tmp_path):
    f=tone(tmp_path/'ref.wav')
    path=library_path(tmp_path)
    lib=add_reference(load_library(path),f,extract_features(f))
    save_library(path,lib)
    loaded=load_library(path)
    assert reference_context(loaded)['count']==1
    loaded['active']=[]
    save_library(path,loaded)
    assert reference_context(load_library(path)) is None
    assert Path(f).is_file()


def test_signature_changes_with_reference(tmp_path):
    path=library_path(tmp_path)
    assert reference_signature(path)=='none'
    save_library(path,load_library(path))
    first=reference_signature(path)
    save_library(path,{'schema':1,'entries':[],'active':['changed']})
    assert reference_signature(path)!=first


def test_candidate_context_reaches_select_and_manual_stays_safe(tmp_path):
    files={n:tone(tmp_path/(n+'.wav'),k) for n,k in [('balanced',220),('vocal-focus',250),('punchy',300)]}
    ref=tone(tmp_path/'reference.wav',260)
    p=library_path(tmp_path)
    save_library(p,add_reference(load_library(p),ref,extract_features(ref)))
    # Simulated Hermes: the actual local model is NOT tested here.
    selected,decision=choose_candidate(files,reference_path=p,
        ask_fn=lambda metrics: {'selected':'vocal-focus','reason':'Mesures valides.'})
    assert selected=='vocal-focus'
    assert decision['reference_used']
    assert len(decision['reference']['candidate_spectral_shares'])==3
    selected,decision=choose_candidate(files,reference_path=p,
        ask_fn=lambda metrics: {'selected':'fake','reason':'invalid'})
    assert selected=='balanced' and decision['mode']=='fallback'
