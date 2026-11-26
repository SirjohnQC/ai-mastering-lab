"""Read-only stem diagnostics and explainable saturation advice.

Recommendations are NOT artifact diagnosis, and never enable processing.
"""
from __future__ import annotations
import math
from pathlib import Path
from .stem_inspector import inspect_audio_file
from .stem_saturation import suggestions

def advise_one(stem_row, inspection):
    """Classify what was actually measured separately from a category preset."""
    category=stem_row['group']
    windows=inspection.get('windows',[])
    if not windows:
        return {'status':'insufficient_data','recommendation':'bypass',
                'reason':'No measurable audio windows.','evidence':{}}
    active=[w for w in windows if w.get('rms_dbfs',-120)>-65]
    if not active:
        return {'status':'quiet','recommendation':'bypass',
                'reason':'Track mostly silent; saturation not justified.','evidence':{}}
    near_clip=sum(w.get('near_clipped_samples',0) for w in windows)
    crest=sorted(w['crest_db'] for w in active)[len(active)//2]
    hf=sum(w.get('hf_ratio_above_10khz',0) for w in active)/len(active)
    evidence={'near_clip_samples':int(near_clip),
              'median_crest_db':round(crest,2),
              'mean_high_frequency_ratio':round(hf,4),
              'analyzed_active_windows':len(active)}
    if any(w.get('nonfinite_audio') for w in windows):
        return {'status':'review','recommendation':'bypass',
                'reason':'Invalid samples require review before FX.','evidence':evidence}
    if near_clip>0:
        return {'status':'review','recommendation':'bypass',
                'reason':'Samples near full scale: saturation could clip; review first.','evidence':evidence}
    if category in ('drums','other'):
        return {'status':'caution','recommendation':'bypass',
                'reason':'Category has transient/unknown content. No automatic saturation suggestion.','evidence':evidence}
    if hf>.22:
        return {'status':'caution','recommendation':'bypass',
                'reason':'Elevated high-frequency energy; saturation might increase harshness.','evidence':evidence}
    if category=='guitars' and crest<7:
        return {'status':'caution','recommendation':'bypass',
                'reason':'Already dense guitar dynamics; audition before adding harmonics.','evidence':evidence}
    if category=='vocals':
        reason='Vocal stem has reasonable headroom: optional subtle Tape preview; check sibilance.'
    elif category=='bass':
        reason='Bass has headroom: optional gentle Tube harmonics; compare at equal level.'
    else:
        reason='Guitar has headroom: optional subtle Tape; already distorted tones may not benefit.'
    return {'status':'candidate','recommendation':'audition_only',
            'reason':reason,'evidence':evidence}

def inspect_and_advise(config):
    results=[]
    for row in suggestions(config):
        analysis=inspect_audio_file(Path(row['file']))
        advice=advise_one(row,analysis)
        results.append({**row,'inspection':{
            'sample_rate':analysis['sample_rate'],'channels':analysis['channels'],
            'duration_ms':analysis['duration_ms'],
            'suspicions':analysis['suspicions'][:12]},
            'advisor':advice})
    return results
