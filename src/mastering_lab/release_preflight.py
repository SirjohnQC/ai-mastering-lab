"""Independent, read-only preflight for a rendered stereo PCM WAV.

This is a technical check, not a Spotify/DistroKid approval or artistic assessment.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone


class PreflightError(RuntimeError):
    pass


def analyze_wav(path, *, measure_loudness=None, write_report=True):
    import numpy as np
    import soundfile as sf

    source = Path(path).resolve()
    if not source.is_file() or source.suffix.lower() != '.wav':
        raise PreflightError('Sélectionne un fichier WAV existant.')
    issues, warnings = [], []
    with sf.SoundFile(str(source), 'r') as wav:
        sample_rate, channels, frames = wav.samplerate, wav.channels, wav.frames
        subtype, fmt = wav.subtype, wav.format
        if sample_rate <= 0 or frames <= 0:
            raise PreflightError('WAV vide ou corrompu.')
        if fmt not in ('WAV', 'WAVEX'):
            issues.append(f'Conteneur WAV ou WAVEX attendu; format observé : {fmt}.')
        if channels != 2:
            issues.append(f'Le fichier doit avoir 2 canaux stéréo; canaux observés : {channels}.')
        if subtype not in ('PCM_24', 'PCM_16'):
            issues.append('Format PCM attendu (16 ou 24 bits); format observé : ' + subtype)
        if subtype != 'PCM_24':
            warnings.append('Pour un export master haute résolution, préférer PCM 24 bits.')
        if sample_rate not in (44100, 48000, 88200, 96000):
            warnings.append(f'Fréquence inhabituelle pour la distribution : {sample_rate} Hz.')
        duration = frames / sample_rate
        if duration < 10:
            warnings.append('Durée inférieure à 10 secondes : vérifier que le morceau est complet.')
        peak = 0.0
        clip_frames = 0
        nonfinite = 0
        n = 0
        power = 0.0
        silence_limit = 10 ** (-60 / 20)
        first_active = None
        last_active = None
        while True:
            audio = wav.read(131072, dtype='float64', always_2d=True)
            if len(audio) == 0:
                break
            nonfinite += int(np.size(audio) - np.count_nonzero(np.isfinite(audio)))
            audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
            amplitudes = np.abs(audio)
            peak = max(peak, float(np.max(amplitudes)))
            clip_frames += int(np.count_nonzero(np.any(amplitudes >= 0.9999, axis=1)))
            power += float(np.sum(audio * audio))
            n += audio.size
            active_indices = np.flatnonzero(np.any(amplitudes >= silence_limit, axis=1))
            if len(active_indices):
                if first_active is None:
                    first_active = (n // channels - len(audio)) + int(active_indices[0])
                last_active = (n // channels - len(audio)) + int(active_indices[-1])
    if nonfinite:
        issues.append('Échantillons non finis détectés.')
    if clip_frames:
        issues.append(f'{clip_frames} frame(s) atteignent le maximum numérique : risque de clipping.')
    if first_active is None:
        issues.append('Le WAV semble entièrement silencieux (seuil −60 dBFS).')
        lead_silence = tail_silence = duration
    else:
        lead_silence = first_active / sample_rate
        tail_silence = (frames - last_active - 1) / sample_rate
        if lead_silence > 2:
            warnings.append(f'Silence initial prolongé : {lead_silence:.2f} s.')
        if tail_silence > 3:
            warnings.append(f'Silence final prolongé : {tail_silence:.2f} s.')
    rms_db = 10 * math.log10(power / n) if power > 0 and n else None
    peak_db = 20 * math.log10(peak) if peak > 0 else None

    # The same FFmpeg EBU R128 analyzer used by Auto Master is run again on export.
    loudness = None
    if measure_loudness is not None:
        try:
            metrics = measure_loudness(source)
            loudness = {'integrated_lufs': float(metrics['input_i']),
                        'true_peak_dbtp': float(metrics['input_tp']),
                        'lra_lu': float(metrics['input_lra'])}
            if not all(math.isfinite(value) for value in loudness.values()):
                raise ValueError('mesures non finies')
            if loudness['true_peak_dbtp'] > -1.0:
                warnings.append('True peak supérieur à −1 dBTP : vérifier l’encodage avec pertes.')
            # -14 LUFS is a normalization reference, NOT a mandatory delivery spec.
        except Exception as exc:
            issues.append(f'Impossible de vérifier LUFS et true peak : {type(exc).__name__}: {exc}')
    else:
        warnings.append('LUFS et true peak non mesurés : FFmpeg requis pour validation complète.')

    status = 'needs_review' if issues else 'technical_pass_with_notes' if warnings else 'technical_pass'
    result = {'schema_version': 1, 'kind': 'release_preflight',
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'source': str(source), 'status': status,
              'file': {'sample_rate': sample_rate, 'channels': channels, 'frames': frames,
                       'duration_seconds': round(duration, 3), 'format': fmt, 'subtype': subtype,
                       'size_bytes': source.stat().st_size},
              'audio': {'sample_peak_dbfs': round(peak_db, 3) if peak_db is not None else None,
                        'rms_dbfs': round(rms_db, 3) if rms_db is not None else None,
                        'clipped_frames': clip_frames, 'nonfinite_samples': nonfinite,
                        'initial_silence_seconds': round(lead_silence, 3),
                        'final_silence_seconds': round(tail_silence, 3)},
              'loudness': loudness, 'issues': issues, 'warnings': warnings,
              'publication_approved': False,
              'scope': ('Contrôle technique uniquement. Vérifier l’écoute, les transitions, la cohérence album, '
                        'les droits, les métadonnées et les exigences du distributeur. '
                        '−14 LUFS est une référence de normalisation, pas une obligation Spotify.')}
    if write_report:
        target = source.with_suffix('.preflight.json')
        temporary = target.with_suffix('.preflight.tmp')
        try:
            temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        result['report_path'] = str(target)
    return result


def run_preflight(path, *, write_report=True):
    import shutil
    from .auto_master import _measure
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise PreflightError('FFmpeg introuvable : redémarre le terminal après installation.')
    return analyze_wav(path, measure_loudness=lambda p: _measure(ffmpeg, p), write_report=write_report)


def format_preflight(result, language='fr'):
    """Localize the user-visible technical summary, not measurement or JSON data."""
    english = language == 'en'
    f, a, loud = result['file'], result['audio'], result['loudness']
    status = result['status']
    if english:
        statuses = {'technical_pass':'Technical pass',
                    'technical_pass_with_notes':'Technical pass with notes',
                    'needs_review':'Needs review'}
        lines = [f"Status: {statuses.get(status, status)}",
                 f"WAV: {f['subtype']} · {f['sample_rate']} Hz · {f['channels']} channels · {f['duration_seconds']:.1f} s",
                 'Sample peak: ' + (f"{a['sample_peak_dbfs']:.2f} dBFS" if a['sample_peak_dbfs'] is not None else 'silence'),
                 f"Frames at digital maximum: {a['clipped_frames']}"]
    else:
        lines = [f"Statut : {status}",
                 f"WAV : {f['subtype']} · {f['sample_rate']} Hz · {f['channels']} canaux · {f['duration_seconds']:.1f} s",
                 'Sample peak : ' + (f"{a['sample_peak_dbfs']:.2f} dBFS" if a['sample_peak_dbfs'] is not None else 'silence'),
                 f"Frames au maximum numérique : {a['clipped_frames']}"]
    if loud:
        lines.extend([
            ('Integrated loudness' if english else 'Loudness intégré')
            + f": {loud['integrated_lufs']:.2f} LUFS",
            f"True peak: {loud['true_peak_dbtp']:.2f} dBTP"])
    if english:
        lines.append('Silence: start %.2f s / end %.2f s' %
                     (a['initial_silence_seconds'], a['final_silence_seconds']))
        if result['issues']:
            lines.append('ISSUES: ' + ' | '.join(_issue_to_english(v) for v in result['issues']))
        if result['warnings']:
            lines.append('WARNINGS: ' + ' | '.join(_issue_to_english(v) for v in result['warnings']))
        lines.extend(['This report does not certify Spotify/DistroKid publication.',
                      'Before release: listen throughout, verify album coherence, credits, artwork and rights.'])
    else:
        lines.append('Silence : début %.2f s / fin %.2f s' %
                     (a['initial_silence_seconds'], a['final_silence_seconds']))
        if result['issues']:
            lines.append('À CORRIGER : ' + ' | '.join(result['issues']))
        if result['warnings']:
            lines.append('À VÉRIFIER : ' + ' | '.join(result['warnings']))
        lines.extend(['Ce rapport ne certifie pas une publication Spotify/DistroKid.',
                      'Avant publication : écoute complète, cohérence album, titres/crédits, artwork et droits.'])
    return '\\n'.join(lines)


def _issue_to_english(message):
    """Translate known preflight messages, preserving their measured values."""
    import re
    text = str(message)
    mapping = (
      ('True peak supérieur à −1 dBTP : vérifier l’encodage avec pertes.',
       'True peak exceeds -1 dBTP: verify lossy encoding.'),
      ('Pour un export master haute résolution, préférer PCM 24 bits.',
       'Prefer 24-bit PCM for a high-resolution master.'),
      ('Durée inférieure à 10 secondes : vérifier que le morceau est complet.',
       'Duration under 10 seconds: verify the track is complete.'),
      ('LUFS et true peak non mesurés : FFmpeg requis pour validation complète.',
       'LUFS and true peak not measured: FFmpeg is required for full validation.'),
      ('Le WAV semble entièrement silencieux (seuil −60 dBFS).',
       'The WAV appears silent (-60 dBFS threshold).'),
      ('Échantillons non finis détectés.',
       'Non-finite samples detected.'),
    )
    for original, translated in mapping:
        if text == original:
            return translated
    patterns = (
      (r'^Silence initial prolongé : (.+) s\\.$', 'Extended leading silence: {} s.'),
      (r'^Silence final prolongé : (.+) s\\.$', 'Extended trailing silence: {} s.'),
      (r'^Fréquence inhabituelle pour la distribution : (.+) Hz\\.$', 'Unusual sample rate for distribution: {} Hz.'),
      (r'^(\\d+) frame\\(s\\) atteignent le maximum numérique : risque de clipping\\.$',
       '{} frames reached the digital maximum: clipping risk.'),
    )
    for pattern, template in patterns:
        match = re.match(pattern, text)
        if match:
            return template.format(*match.groups())
    # Never silently invent a translation for a diagnostic we cannot parse.
    return 'Original diagnostic: ' + text
