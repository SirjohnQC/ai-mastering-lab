import pathlib, sys, subprocess, math, wave, shutil
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab import reference_learning as rl

def test_reference_mp3_real(tmp_path):
    if not shutil.which('ffmpeg'):
        return
    wav=tmp_path/'ref.wav'; mp3=tmp_path/'ref.mp3'
    import numpy as np, soundfile as sf
    sr=44100
    seconds=3
    x=(0.12*np.sin(2*np.pi*440*np.arange(sr*seconds)/sr)).astype('float32')
    sf.write(wav,x,sr)
    subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(wav),str(mp3)],check=True)
    f=rl.extract_features(mp3)
    assert f['source']==str(mp3.resolve())
    assert f['sample_rate']==sr
    assert abs(sum(f['spectral_shares'])-1.0)<0.0001
    assert f['duration_seconds']>=2.0

def test_reference_mp3_fallback(tmp_path,monkeypatch):
    import numpy as np, soundfile as sf
    sr=44100
    wav=tmp_path/'ref.wav'; mp3=tmp_path/'ref.mp3'
    sf.write(wav, 0.1*np.sin(2*np.pi*300*np.arange(sr*3)/sr), sr)
    subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(wav),str(mp3)], check=True)
    original=rl._extract_pcm_features
    def fail_mp3(path,**kw):
        if pathlib.Path(path).suffix=='.mp3':
            raise RuntimeError('libsndfile old version')
        return original(path,**kw)
    monkeypatch.setattr(rl,'_extract_pcm_features',fail_mp3)
    result=rl.extract_features(mp3)
    assert result['source']==str(mp3.resolve())
    assert result['sampled_seconds']>0

def test_ui_contract():
    text=(pathlib.Path(__file__).resolve().parents[1]/'src/mastering_lab/auto_studio_ui.py').read_text()
    for x in ('songTitleMaster','songTitleImport','def _sync_title_from_import','def _sync_title_from_master','self._master_song_title = self._song_title_for_export()','def _open_references'):
        assert x in text
    refui=(pathlib.Path(__file__).resolve().parents[1]/'src/mastering_lab/reference_learning_ui.py').read_text()
    assert '*.mp3' in refui
