from pathlib import Path
import sys
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.live_ab import LiveAB, prepare_tracks


def create_pair(tmp_path):
    rate=48000
    a=tmp_path/'a.wav'; b=tmp_path/'b.wav'
    sf.write(a,np.full((rate,2),.15,dtype=np.float32),rate)
    sf.write(b,np.full((rate,2),.45,dtype=np.float32),rate)
    return {'original':a,'warm':b}


def test_switch_keeps_position_and_crossfades(tmp_path):
    paths=create_pair(tmp_path)
    engine=LiveAB(fade_ms=25)
    engine.load(paths)
    engine.playing=True
    first=engine.render_block(4800)
    assert np.isclose(first.mean(),.15,atol=.002)
    cursor=engine.cursor
    engine.choose('warm')
    assert engine.cursor==cursor
    transition=engine.render_block(1200)
    assert transition[0,0] > .15 and transition[0,0] < .20
    assert np.isclose(transition[-1,0],.45,atol=.002)
    assert engine.cursor==6000
    assert np.isclose(engine.render_block(1000).mean(),.45,atol=.002)
    engine.close()


def test_seek_and_marker_end(tmp_path):
    e=LiveAB();e.load(create_pair(tmp_path));e.seek(300)
    assert e.position_ms==300
    e.set_range_end(350);e.playing=True
    chunk=e.render_block(4800)
    assert e.position_ms==350
    assert not e.playing
    assert np.allclose(chunk[2400:],0)


def test_mismatch_rejected(tmp_path):
    paths=create_pair(tmp_path)
    sf.write(paths['warm'],np.zeros((48000,2),dtype=np.float32),44100)
    try:
        prepare_tracks(paths)
    except ValueError as exc:
        assert 'Sample rate mismatch' in str(exc)
    else:
        assert False, 'Expected sample rate mismatch'


def test_gain_applied_to_audition_only(tmp_path):
    paths=create_pair(tmp_path)
    tracks,rate=prepare_tracks(paths,{'warm':.5})
    assert rate==48000
    assert np.isclose(tracks['warm'][100,0],.225,atol=.002)
    data,_=sf.read(str(paths['warm']))
    assert np.isclose(data[100,0],.45,atol=.002)
