from pathlib import Path
import numpy as np
import soundfile as sf
from mastering_lab.stem_inspector import (classify_stem, discover_stems, default_stem_folder,
                                          inspect_audio_file, inspect_folder, save_report)


def test_categories():
    assert classify_stem(Path('Lead Vocals.wav')) == 'vocals'
    assert classify_stem(Path('electric guitar.wav')) == 'guitars'
    assert classify_stem(Path('Drums.wav')) == 'drums'
    assert classify_stem(Path('Bass.wav')) == 'bass'


def test_discover_folder(tmp_path):
    (tmp_path/'hi.wav').touch()
    (tmp_path/'x.mp3').touch()
    (tmp_path/'unused.txt').touch()
    assert [x.name for x in discover_stems(tmp_path)] == ['hi.wav', 'x.mp3']
    assert default_stem_folder(tmp_path,Path('song.wav')) == tmp_path/'sound'/'stems'


def test_diagnostics_and_report(tmp_path):
    folder=tmp_path/'sound'/'stems'/'Song'; folder.mkdir(parents=True)
    sr=16000
    t=np.arange(sr*5)/sr
    wave=.12*np.sin(2*np.pi*440*t)
    wave[sr*2:sr*3]=0
    wave[sr*4:sr*5]=1.0
    sf.write(folder/'Vocals.wav',wave,sr,subtype='FLOAT')
    info=inspect_audio_file(folder/'Vocals.wav',window_seconds=1)
    assert info['sample_rate']==sr and info['duration_ms']==5000
    assert len(info['windows'])==5
    assert any(x['issue']=='possible_clipping' for x in info['suspicions'])
    report=inspect_folder(tmp_path,folder,Path('Song.wav'))
    saved=save_report(tmp_path,report,Path('Song.wav'))
    assert saved.is_file() and 'stems' in saved.read_text()
    assert all(x['status']=='needs_human_review' for x in info['suspicions'])


def test_short_silence_no_false_clipping(tmp_path):
    path=tmp_path/'Bass.wav';sf.write(path,np.zeros(4000,dtype=np.float32),8000)
    info=inspect_audio_file(path)
    assert not info['suspicions']
