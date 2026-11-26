"""Opt-in selective saturation recommendations and cache identity for album stems.

Recommendations are deliberately heuristic based on filename/group, not claims
of detecting or repairing AI artifacts. No processing occurs unless approved.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .album_saturation_preview import validate_settings
from .auto_mix_candidates import _group

SAFE_DEFAULTS = {
    'vocals': {'style':'tape','drive':0.6,'mix':0.12,
               'why':'Optional gentle harmonics on voices; audition sibilance carefully.'},
    'bass': {'style':'tube','drive':0.7,'mix':0.16,
             'why':'Optional harmonic presence for bass on smaller speakers.'},
    'guitars': {'style':'tape','drive':0.5,'mix':0.12,
                'why':'Optional gentle harmonic texture; distorted guitars may need none.'},
    'drums': {'style':'softclip','drive':0.4,'mix':0.08,
              'why':'Usually bypass: cymbals and transients can get harsher.'},
    'other': {'style':'tape','drive':0.4,'mix':0.08,
              'why':'Bypass by default until this stem is identified by ear.'},
}


def suggestions(config):
    """Return stable file-specific candidates, all DISABLED by default."""
    return [
        {'file':str(Path(row['file']).resolve()),'group':_group(row),
         'enabled':False,**SAFE_DEFAULTS[_group(row)]}
        for row in config.get('tracks',[])
    ]


def validated_selections(config, selections):
    """Canonical JSON-compatible approved treatment map, never source writes."""
    if selections is None:
        return {}
    if not isinstance(selections,dict):
        raise ValueError('Stem saturation selections must be a dictionary.')
    all_sources={str(Path(row['file']).resolve()) for row in config['tracks']}
    canonical={}
    for key,value in selections.items():
        path=str(Path(key).resolve())
        if path not in all_sources or not isinstance(value,dict):
            raise ValueError('Unknown or invalid stem saturation selection.')
        if not value.get('enabled',False):
            continue
        style,drive,mix=validate_settings(value.get('style'),value.get('drive'),value.get('mix'))
        canonical[path]={'style':style,'drive':drive,'mix':mix,'enabled':True}
    return dict(sorted(canonical.items()))


def selection_signature(selections):
    normalized=selections or {}
    if not normalized:
        return 'none'
    raw=json.dumps(normalized,sort_keys=True,ensure_ascii=False,
                   separators=(',',':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def prepare_selected_stems(config, selections, dest, *, stop=None, processor=None):
    """Create one locally cached wet print per approved stem, once per album job.

    Existing source file always remains untouched. Mixer consumes the aligned
    printed WAVs through its explicit prepared map, not by matching filenames.
    """
    from .album_saturation_preview import process_saturation_wav
    import soundfile as sf

    selected=validated_selections(config,selections)
    if not selected:
        return {},[]
    destination=Path(dest).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    printer=processor or process_saturation_wav
    prepared={}
    rows=[]
    for index,track in enumerate(config['tracks']):
        source=Path(track['file']).resolve()
        entry=selected.get(str(source))
        if entry is None:
            continue
        if stop is not None and stop.is_set():
            from .auto_master import MasteringCancelled
            raise MasteringCancelled('Saturation stem interrompue entre les pistes.')
        stat=source.stat()
        identity=json.dumps({'source':str(source),'size':stat.st_size,
            'mtime_ns':stat.st_mtime_ns,'params':entry,
            'policy':'selective-saturation-v1'},sort_keys=True)
        key=hashlib.sha256(identity.encode('utf-8')).hexdigest()[:18]
        out=destination/f'stem-{index}-{key}.wav'
        if not out.is_file():
            partial=destination/f'.stem-{index}-{key}.partial.wav'
            try:
                printer(source,partial,style=entry['style'],
                        drive=entry['drive'],mix=entry['mix'])
                with sf.SoundFile(str(source)) as original, sf.SoundFile(str(partial)) as wet:
                    if (original.samplerate!=wet.samplerate or
                            original.channels!=wet.channels or original.frames!=wet.frames):
                        raise ValueError('Saturated stem has changed audio timing or channels.')
                partial.replace(out)
            finally:
                partial.unlink(missing_ok=True)
        prepared[str(index)]=str(out)
        rows.append({'source':str(source),'prepared':str(out),**entry})
    return prepared,rows
