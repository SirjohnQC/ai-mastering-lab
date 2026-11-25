"""Read-only input-activity inspection around FabFilter threshold readback.

Measures stereo source PCM in small fixed windows. These are source signal
statistics, not Pro-C 3 detector envelopes or gain-reduction telemetry.
No files are modified. Do not upload reports or private WAV to GitHub.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

WINDOW_MS = 10
MAX_SECONDS = 600


def inspect_threshold_activity(source: Path, threshold_db: float | None) -> dict:
    """Estimate how often input peaks/RMS cross the *read-back* threshold.

    A 10 ms peak event can be short even when the plugin uses RMS detection,
    knee, attack, hold and release. Never equate threshold crossings with GR.
    """
    if threshold_db is None:
        return {'status':'unavailable','reason':'Seuil physique Pro-C 3 non confirmé.'}
    if isinstance(threshold_db, bool) or not isinstance(threshold_db, (float,int)) or not math.isfinite(threshold_db):
        raise ValueError('Non-finite plugin threshold.')
    if not -120.0 <= threshold_db <= 24.0:
        raise ValueError('Unexpected physical threshold.')
    path = Path(source).resolve(strict=True)
    with sf.SoundFile(str(path)) as audio:
        if audio.channels != 2 or audio.samplerate != 48000 or not 0 < audio.frames <= audio.samplerate*MAX_SECONDS + audio.samplerate:
            raise ValueError('Unsupported source format/length for activity inspector.')
        step = audio.samplerate * WINDOW_MS // 1000
        threshold_linear = 10.0 ** (threshold_db/20.0)
        peak_count = rms_count = 0
        longest_peak = longest_rms = current_peak = current_rms = 0
        count = 0
        above_peak_windows = []
        max_peak = 0.0
        # For bounded reports, retain only the first few representative crossings.
        while True:
            data = audio.read(step, dtype='float32', always_2d=True)
            if len(data) < step:
                break
            if not np.isfinite(data).all():
                raise ValueError('Invalid PCM input samples.')
            peak = float(np.max(np.abs(data)))
            rms = float(np.sqrt(np.mean(data.astype('float64')**2)))
            max_peak = max(max_peak,peak)
            peak_hit = peak >= threshold_linear
            rms_hit = rms >= threshold_linear
            peak_count += int(peak_hit)
            rms_count += int(rms_hit)
            current_peak = current_peak+1 if peak_hit else 0
            current_rms = current_rms+1 if rms_hit else 0
            longest_peak = max(longest_peak,current_peak)
            longest_rms = max(longest_rms,current_rms)
            if peak_hit and len(above_peak_windows) < 4:
                above_peak_windows.append(count * WINDOW_MS)
            count += 1
    if count == 0:
        return {'status':'unavailable','reason':'Source trop courte pour les fenêtres de 10 ms.'}
    return {
        'status':'measured','threshold_db':round(float(threshold_db),3),
        'window_ms':WINDOW_MS, 'analyzed_windows':count,
        'peak_above_threshold_pct':round(100*peak_count/count,3),
        'rms_above_threshold_pct':round(100*rms_count/count,3),
        'longest_peak_run_ms':longest_peak*WINDOW_MS,
        'longest_rms_run_ms':longest_rms*WINDOW_MS,
        'first_peak_crossings_ms':above_peak_windows,
        'source_peak_dbfs':round(20*math.log10(max(max_peak,1e-12)),3),
        'note':'PCM input threshold crossings, NOT actual Pro-C 3 gain reduction.'
    }


def interpret_activity(activity: dict, delta_db: float | None) -> dict:
    """Cautious evidence summary, never a diagnosis of prior compression."""
    if activity.get('status') != 'measured':
        return {'status':'unknown','message':'Activité au seuil inconnue : seuil relu ou WAV indisponible.'}
    peak_pct = activity['peak_above_threshold_pct']
    rms_pct = activity['rms_above_threshold_pct']
    longest = activity['longest_peak_run_ms']
    subtle = isinstance(delta_db,(int,float)) and not isinstance(delta_db,bool) and math.isfinite(delta_db) and abs(delta_db)<0.15
    if peak_pct == 0:
        message = 'Aucune fenêtre de 10 ms ne dépasse le seuil en crête. Peu de compression attendue avec ce seuil.'
        status = 'below_threshold'
    elif rms_pct < 0.1 and longest <= 20:
        message = 'Dépassements surtout très brefs en crête, sans niveau RMS durable au-dessus du seuil. L’attaque peut limiter l’effet.'
        status = 'brief_peaks'
    elif rms_pct >= 5 or activity['longest_rms_run_ms'] >= 100:
        message = 'Plusieurs fenêtres RMS dépassent le seuil. Si le WAV reste presque inchangé, vérifier la réaction réelle de Pro-C 3 plutôt que supposer un mix déjà compressé.'
        status = 'sustained_input'
    else:
        message = 'Le seuil est dépassé par moments, mais ces mesures ne suffisent pas à conclure sur la réduction de gain.'
        status = 'intermittent'
    if subtle and status == 'sustained_input':
        message += ' Le rendu Gentle présente justement une différence RMS globale très faible.'
    return {'status':status,'message':message}
