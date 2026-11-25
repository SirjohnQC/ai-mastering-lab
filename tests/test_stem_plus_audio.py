import numpy as np
from mastering_lab.stem_plus_audio import mix_window, LiveStemMixer, gain_pan

def test_solo_mute_and_multiple_selection():
    x=np.ones((8,2),dtype=np.float32)*.1
    states=[{'solo':False,'mute':False,'gain_db':0,'pan':0,'eq':False} for _ in range(3)]
    a=mix_window([x,x,x],{},states,0,8)
    assert np.allclose(a, .3*10**(-12/20))
    states[0]['solo']=True; states[2]['solo']=True
    b=mix_window([x,x,x],{},states,0,8)
    assert np.allclose(b,.2*10**(-12/20))
    states[2]['mute']=True
    c=mix_window([x,x,x],{},states,0,8)
    assert np.allclose(c,.1*10**(-12/20))

def test_processed_toggle():
    x=np.ones((16,2),dtype=np.float32)*.05
    wet=np.ones((16,2),dtype=np.float32)*.2
    s=[{'eq':False}]
    dry=mix_window([x],{0:wet},s,0,16)
    s[0]['eq']=True
    changed=mix_window([x],{0:wet},s,0,16)
    assert np.mean(changed)>3*np.mean(dry)

def test_playhead_persists_on_live_change():
    e=LiveStemMixer()
    e.dry=[np.ones((4000,2),dtype=np.float32)*.1]
    e.states=[{'gain_db':0,'pan':0,'mute':False,'solo':False,'eq':False}]
    e.rate=1000;e.fade_frames=25
    e.render_block(100)
    e.update_states([{'gain_db':-4,'pan':0,'mute':False,'solo':False,'eq':False}])
    e.render_block(100)
    assert e.cursor==200 and e.old_states is None

def test_pan_neutral_preserves_stereo():
    x=np.array([[.3,.6]],dtype=np.float32)
    assert np.allclose(gain_pan(x,0,0),x)


def test_master_monitor_gain_is_separate_from_source():
    e=LiveStemMixer()
    e.dry=[np.ones((2000,2),dtype=np.float32)*.1]
    e.states=[{'gain_db':0,'pan':0,'mute':False,'solo':False,'eq':False}]
    e.rate=1000
    e.set_master_gain(-6)
    out=e.render_block(50)
    assert np.allclose(out,.1*10**(-18/20),atol=1e-6)
    assert np.all(e.dry[0]==.1*np.ones((2000,2),dtype=np.float32))

def test_meters_obey_mute_solo_and_output_gain():
    e=LiveStemMixer()
    x=np.ones((2500,2),dtype=np.float32)*.1
    e.dry=[x,x]
    e.states=[{'gain_db':0,'pan':0,'mute':False,'solo':True,'eq':False},
              {'gain_db':0,'pan':0,'mute':False,'solo':False,'eq':False}]
    levels=e.meter_levels()
    assert -33<levels[0]<-31
    assert levels[1]==-90
    e.set_master_gain(3)
    assert abs(e.meter_levels()[0]-levels[0]-3)<.001

def test_master_gain_bounds():
    import pytest
    e=LiveStemMixer()
    for bad in (-31,7,float('nan')):
        with pytest.raises(ValueError):e.set_master_gain(bad)
