"""Synchronized, non-destructive STEM+ monitoring.  This is NOT a final mastering renderer.

Source audio is loaded in RAM for responsive solo/mute/processed switching.
The callback returns stereo float32 and applies fixed monitoring headroom.
"""
from __future__ import annotations
from pathlib import Path
import math
import threading
import numpy as np
import soundfile as sf


def load_stems(paths: list[Path], max_bytes: int = 1_500_000_000):
    if not paths:
        raise ValueError('No stems selected')
    tracks, rate, size = [], None, 0
    for path in paths:
        with sf.SoundFile(str(path)) as f:
            if f.channels not in (1,2):
                raise ValueError(f'{path.name}: mono/stereo only')
            if rate is not None and f.samplerate != rate:
                raise ValueError(f'{path.name}: sample rate differs. Align/resample in Cubase first.')
            rate = f.samplerate
            bytes_needed = len(f) * f.channels * 4
            if size + bytes_needed > max_bytes:
                raise MemoryError('Stems require too much RAM; use shorter exports for live preview.')
            data = f.read(dtype='float32', always_2d=True)
            if not np.isfinite(data).all():
                raise ValueError(f'{path.name}: non-finite audio samples')
            size += bytes_needed
            tracks.append(data)
    lengths = [len(t) for t in tracks]
    if max(lengths)-min(lengths) > round(.05 * rate):
        raise ValueError('Stems differ in duration by >50 ms. Align in Cubase first.')
    frames = max(lengths)
    tracks = [np.pad(t, ((0, frames-len(t)),(0,0))) for t in tracks]
    return tracks, rate


def gain_pan(stem: np.ndarray, gain_db: float, pan: float) -> np.ndarray:
    gain = 10 ** (gain_db / 20)
    if stem.shape[1] == 1:
        angle = (pan + 1)*math.pi/4
        return np.column_stack((stem[:,0]*math.cos(angle),stem[:,0]*math.sin(angle))) * gain
    return stem * np.array([min(1.,1.-pan),min(1.,1.+pan)], dtype=np.float32) * gain


def mix_window(dry: list[np.ndarray], wet: dict[int,np.ndarray], states: list[dict], start: int, frames: int, headroom_db: float=-12.) -> np.ndarray:
    """Pure block mixer for tests and stream callback; no mutation of source arrays."""
    result=np.zeros((frames,2), dtype=np.float32)
    if not dry or not states: return result
    solo=any(s.get('solo',False) and not s.get('mute',False) for s in states)
    for idx,(audio,state) in enumerate(zip(dry,states)):
        if state.get('mute',False) or (solo and not state.get('solo',False)): continue
        selected=wet.get(idx,audio) if state.get('eq',False) else audio
        if start>=len(selected): continue
        section=selected[start:min(start+frames,len(selected))]
        if len(section):
            result[:len(section)] += gain_pan(section,float(state.get('gain_db',0)),float(state.get('pan',0)))
    result *= 10 ** (headroom_db/20)
    return result


class LiveStemMixer:
    def __init__(self, fade_ms:float=25):
        self.lock=threading.RLock();self.dry=[];self.wet={};self.paths=[]
        self.rate=48000;self.cursor=0;self.states=[];self.old_states=None
        self.fade_ms=fade_ms;self.fade_progress=0;self.fade_frames=1200
        self.playing=False;self.stream=None;self.peak=0.0;self.master_gain_db=0.0

    def load(self, paths: list[Path], states: list[dict]|None=None):
        audio,rate=load_stems(paths)
        self.close()
        with self.lock:
            self.dry=audio;self.paths=list(paths);self.rate=rate;self.cursor=0;self.wet={}
            self.states=[dict(s) for s in states] if states else [dict(gain_db=0.,pan=0.,mute=False,solo=False,eq=False) for _ in paths]
            self.old_states=None;self.fade_frames=max(1,round(rate*self.fade_ms/1000));self.peak=0.

    @property
    def duration_ms(self):
        with self.lock:return round(1000*len(self.dry[0])/self.rate) if self.dry else 0
    @property
    def position_ms(self):
        with self.lock:return round(1000*self.cursor/self.rate)

    def update_states(self, states:list[dict]):
        with self.lock:
            if len(states)!=len(self.dry):raise ValueError('Missing tracks')
            for s in states:
                if not (-18<=float(s.get('gain_db',0))<=18 and -1<=float(s.get('pan',0))<=1):
                    raise ValueError('Invalid gain or pan')
            if self.states != states:
                # Transition from current mix; avoid clicks on solo/mute/FX toggles.
                self.old_states=[dict(s) for s in self.states]
                self.fade_progress=0
                self.states=[dict(s) for s in states]

    def set_master_gain(self, gain_db: float):
        if not math.isfinite(gain_db) or not -30 <= gain_db <= 6:
            raise ValueError("Master monitor gain must be between -30 and +6 dB")
        with self.lock: self.master_gain_db=float(gain_db)

    def meter_levels(self, frames: int=2048) -> list[float]:
        """Fast read-only dBFS estimates per currently audible track, for GUI meters.
        Not a loudness or true-peak measurement. Uses a short window around playhead.
        """
        with self.lock:
            if not self.dry: return []
            solo=any(s.get("solo") and not s.get("mute") for s in self.states)
            start=max(0,min(self.cursor,len(self.dry[0])-1))
            levels=[]
            for i,(audio,state) in enumerate(zip(self.dry,self.states)):
                if state.get("mute") or (solo and not state.get("solo")):
                    levels.append(-90.0);continue
                selected=self.wet.get(i,audio) if state.get("eq") else audio
                part=selected[start:start+frames]
                if not len(part):levels.append(-90.0);continue
                amplitude=float(np.max(np.abs(part)))
                gain=float(state.get("gain_db",0))+self.master_gain_db-12.0
                levels.append(max(-90.0,20*math.log10(max(amplitude,1e-9))+gain))
            return levels

    def set_processed(self, index:int,path:Path):
        with self.lock:
            if not self.dry:raise ValueError('Load stems first')
            length=len(self.dry[index]);rate=self.rate
        arr,sr=sf.read(str(path),dtype='float32',always_2d=True)
        if sr!=rate or arr.shape[1]!=self.dry[index].shape[1] or abs(len(arr)-length)>round(.05*rate):
            raise ValueError(f'Processed {path.name} sample rate, channels or duration differs')
        arr=np.pad(arr[:length],((0,max(0,length-len(arr))),(0,0)))
        with self.lock:self.wet[index]=arr

    def seek(self,position_ms:int):
        with self.lock:
            if self.dry:self.cursor=min(len(self.dry[0]),max(0,round(position_ms*self.rate/1000)))
            self.old_states=None

    def render_block(self,frames:int)->np.ndarray:
        with self.lock:
            if not self.dry:return np.zeros((frames,2),dtype=np.float32)
            start=self.cursor;limit=len(self.dry[0]);valid=max(0,min(frames,limit-start))
            out=mix_window(self.dry,self.wet,self.states,start,frames,headroom_db=-12+self.master_gain_db)
            if self.old_states is not None:
                old=mix_window(self.dry,self.wet,self.old_states,start,frames,headroom_db=-12+self.master_gain_db)
                alpha=np.clip((np.arange(frames,dtype=np.float32)+self.fade_progress)/self.fade_frames,0,1)[:,None]
                out=old*(1-alpha)+out*alpha
                self.fade_progress+=frames
                if self.fade_progress>=self.fade_frames:self.old_states=None
            self.cursor+=valid
            if self.cursor>=limit:self.playing=False
            self.peak=max(self.peak,float(np.max(np.abs(out))) if out.size else 0)
            # Monitoring only: prevent unsafe digital clipping; no limiting in stored renders.
            return np.clip(out,-1,1).astype(np.float32)

    def play(self):
        import sounddevice as sd
        with self.lock:
            if not self.dry:raise ValueError('Load stems before playback')
            if self.cursor>=len(self.dry[0]):self.cursor=0
            if self.stream is None:
                def callback(outdata,frames,_time,_status):
                    with self.lock:
                        outdata[:]=self.render_block(frames) if self.playing else 0
                self.stream=sd.OutputStream(channels=2,samplerate=self.rate,dtype='float32',blocksize=1024,callback=callback)
                self.stream.start()
            self.playing=True

    def pause(self):
        with self.lock:self.playing=False

    def stop(self):
        with self.lock:self.playing=False;self.cursor=0;self.old_states=None

    def close(self):
        with self.lock:stream=self.stream;self.stream=None;self.playing=False
        if stream is not None:stream.stop();stream.close()
