from pathlib import Path
import importlib.util
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
p = Path(__file__).resolve().parents[1] / 'scripts' / 'reference_eq.py'
spec = importlib.util.spec_from_file_location('reference_eq_mp3', p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def test_discover_mp3_reference_and_wav_source(tmp_path):
    (tmp_path/'ref').mkdir(); (tmp_path/'source').mkdir()
    (tmp_path/'ref'/'master.MP3').touch(); (tmp_path/'source'/'track.wav').touch()
    sources, ref = mod.discover(tmp_path, None, None)
    assert ref.name == 'master.MP3'
    assert [p.name for p in sources] == ['track.wav']

def test_wav_passes_through(tmp_path):
    wav = tmp_path/'song.wav'; wav.touch()
    assert mod.decode_for_processing(wav, tmp_path, 'x') == wav

def test_decode_mp3(tmp_path):
    import shutil, subprocess, wave, struct, math
    import pytest
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg not installed')
    original = tmp_path/'tone.wav'
    with wave.open(str(original), 'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(48000)
        data = b''.join(struct.pack('<hh', int(7000*math.sin(i*2*math.pi*440/48000)), int(7000*math.sin(i*2*math.pi*440/48000))) for i in range(48000))
        wf.writeframes(data)
    mp3 = tmp_path/'tone.mp3'
    subprocess.run(['ffmpeg','-loglevel','error','-y','-i',str(original),str(mp3)],check=True)
    out = mod.decode_for_processing(mp3, tmp_path, 'reference')
    assert out.is_file() and out.stat().st_size>1000
    import soundfile as sf
    data, sr = sf.read(out)
    assert sr == 48000 and data.shape[1] == 2
