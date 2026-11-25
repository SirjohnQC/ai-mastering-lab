"""Conservative, explainable *proposals* for per-stem FX chains.

This is not a trained neural classifier, nor does it programmatically dial in
unverified VST parameters. Suggestions are based on measurable audio features,
stem categories, and the user's selected plugin roles. Originals are unchanged.
"""
from __future__ import annotations
from pathlib import Path
import math
import numpy as np
import soundfile as sf

def analyze_stem(path: Path, seconds: float = 24.0) -> dict:
    """Analyze bounded excerpts (beginning, middle, end) of a mono/stereo WAV/FLAC/AIFF.

    MP3 requires prior decoding by the host's existing FFmpeg utility.
    """
    path = Path(path)
    with sf.SoundFile(str(path)) as f:
        sr, frames, channels = f.samplerate, len(f), f.channels
        if channels not in (1,2) or frames < 1 or sr <= 0:
            raise ValueError(f'Invalid mono/stereo stem: {path.name}')
        excerpt = max(1, int(seconds/3 * sr))
        chunks=[]
        for center in (0, frames//2, max(0, frames-excerpt)):
            f.seek(max(0,min(center, frames-excerpt)))
            block=f.read(min(excerpt,frames),dtype='float32',always_2d=True)
            if len(block):chunks.append(block)
    if not chunks:raise ValueError('No audio')
    data=np.concatenate(chunks,axis=0)
    mono=np.mean(data,axis=1,dtype=np.float64)
    peak=float(np.max(np.abs(data)))
    rms=float(np.sqrt(np.mean(mono**2)))
    eps=1e-10
    # Frame-level loudness variation; diagnostic only, not integrated LUFS.
    n=max(256,int(sr*.1)); count=len(mono)//n
    frame_rms=np.sqrt(np.mean(mono[:count*n].reshape(count,n)**2,axis=1)) if count else np.array([rms])
    p10,p90=np.percentile(20*np.log10(frame_rms+eps),[10,90])
    # FFT sampling avoids accumulating all data into one enormous transform.
    fft_size=8192
    psd=np.zeros(fft_size//2+1,dtype=np.float64)
    for block in np.array_split(mono,min(32,max(1,len(mono)//fft_size))):
        if len(block)<512:continue
        seg=block[:fft_size]
        window=np.hanning(len(seg))
        p=np.abs(np.fft.rfft(seg*window,n=fft_size))**2
        psd+=p
    freqs=np.fft.rfftfreq(fft_size,1/sr)
    def share(low,high):
        return float(psd[(freqs>=low)&(freqs<min(high,sr/2))].sum()/(psd.sum()+eps))
    return {'sample_rate':sr,'duration_s':round(frames/sr,3),'peak_dbfs':round(20*math.log10(peak+eps),2),
            'rms_dbfs':round(20*math.log10(rms+eps),2),
            'crest_db':round(20*math.log10((peak+eps)/(rms+eps)),2),
            'level_variation_db':round(float(p90-p10),2),
            'low_share':round(share(20,180),4),
            'low_mid_share':round(share(180,600),4),
            'presence_share':round(share(2000,6000),4),
            'high_share':round(share(8000,18000),4),
            'note':'Measured on short excerpts; estimates are not auditory defect detection.'}

def suggest_chain(category: str, metrics: dict, roles: dict[str,str], *, name: str='') -> dict:
    """Return safely reviewable, disabled-by-default FX recommendations."""
    category=(category or 'other').lower()
    name=name.lower()
    if 'vocal' in name:category='vocals'
    elif 'drum' in name or 'percussion' in name:category='drums'
    elif 'bass' in name:category='bass'
    elif 'guitar' in name:category='guitars'
    reasons=[]; steps=[]
    def add(role,why):
        plugin=str(roles.get(role,'')).strip()
        if not plugin or not Path(plugin).exists():return
        steps.append({'role':role,'plugin':plugin,'enabled':False,'state_file':'',
                      'parameter_overrides':[],'suggested_reason':why})
        reasons.append(why)
    if category in ('vocals','guitars','bass','drums'):
        add('corrective_eq',f'{category}: EQ correctif à ajuster selon le contexte du mix')
    variation=metrics.get('level_variation_db',0)
    crest=metrics.get('crest_db',0)
    if category in ('vocals','bass') and variation>8:
        add('compression',f'Variations de niveau mesurées (~{variation:.1f} dB) : compression légère à auditionner')
    elif category=='drums' and crest>17:
        add('compression',f'Transitoires marqués (crest ~{crest:.1f} dB) : tester compression parallèle, ne pas écraser les attaques')
    if category in ('vocals','guitars') and metrics.get('presence_share',0)>0.4:
        add('resonance','Présence 2–6 kHz importante : vérifier à l’oreille les résonances avant tout traitement')
    # Reverb is NOT suggested in the serial chain: the current renderer rejects tails.
    warnings=[]
    if metrics.get('peak_dbfs',-99)>-1:warnings.append('Crêtes proches de 0 dBFS : vérifier clipping et marge')
    if category=='other':warnings.append('Catégorie imprécise : inspecter le stem avant de choisir une chaîne')
    return {'category':category,'metrics':metrics,'fx_chain':steps,'reasons':reasons,'warnings':warnings,
            'review_required':True,'automatic_parameter_tuning':False}

def gentle_eq_moves(metrics:dict) -> list[dict]:
    """Conservative starting moves only when an unusually strong frequency region is measured.

    These are *not* evidence of AI artifacts or necessarily musical problems.
    """
    moves=[]
    if metrics.get('low_mid_share',0)>0.33:
        moves.append({'center_hz':350,'recommended_gain_db':-0.7})
    if metrics.get('presence_share',0)>0.42:
        moves.append({'center_hz':3400,'recommended_gain_db':-0.6})
    if metrics.get('high_share',0)>0.20:
        moves.append({'center_hz':11000,'recommended_gain_db':-0.5})
    return moves

def suggest_project(tracks:list[dict],roles:dict[str,str]) -> list[dict]:
    proposals=[]
    for index,track in enumerate(tracks):
        path=Path(track['file'])
        metrics=analyze_stem(path)
        p=suggest_chain(str(track.get('category','other')),metrics,roles,name=path.stem)
        p['eq_moves']=gentle_eq_moves(metrics)
        proposals.append({'index':index,'file':str(path),'name':path.stem,**p})
    return proposals
