"""Read-only, streaming technical measurements and optional Ollama analysis for Auto Mix WAVs.

No signal quality, subjective winner or master compliance is inferred from RMS alone.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen
import numpy as np
import soundfile as sf
from .mix_comparison import load_comparison, VARIANT_ORDER
from .ai_review import _local_endpoint, AIReviewError


def analyze_wav(path: str | Path, *, blocksize: int = 65536) -> dict:
    """Whole-file peak/RMS/crest/correlation plus sample-based spectral shares.

    Spectral shares are based on a small reproducible set of sample windows and
    are descriptive, not psychoacoustic loudness or an objective mix-quality score.
    """
    with sf.SoundFile(str(path)) as file:
        if file.channels != 2 or file.frames <= 0 or file.samplerate <= 0:
            raise ValueError('Fichier stéréo non vide requis.')
        count = 0
        squares = 0.0
        peak = 0.0
        clipped = 0
        sums = np.zeros(2, dtype=np.float64)
        sum_sq = np.zeros(2, dtype=np.float64)
        cross = 0.0
        fft_windows = []
        # Fixed points evenly spread across the entire song; bounded memory.
        window_size = min(16384, file.frames)
        points = np.linspace(0, max(0, file.frames-window_size), 16, dtype=np.int64)
        for position in points:
            file.seek(int(position))
            buf = file.read(window_size, dtype='float64', always_2d=True)
            if len(buf) >= 64:
                mono = buf.mean(axis=1)
                fft_windows.append(mono[:len(mono)] * np.hanning(len(mono)))
        file.seek(0)
        while True:
            x = file.read(blocksize, dtype='float64', always_2d=True)
            if not len(x): break
            if not np.isfinite(x).all(): raise ValueError('Échantillons non finis dans le WAV.')
            count += len(x)
            squares += float(np.sum(x * x))
            peak = max(peak, float(np.max(np.abs(x))))
            clipped += int(np.count_nonzero(np.abs(x) >= 1.0))
            sums += x.sum(axis=0)
            sum_sq += (x*x).sum(axis=0)
            cross += float(np.sum(x[:,0]*x[:,1]))
        rms = math.sqrt(squares / (2 * count))
        mean = sums / count
        var = np.maximum(0.0, sum_sq/count - mean*mean)
        cov = cross/count - mean[0]*mean[1]
        corr = float(cov / math.sqrt(var[0]*var[1])) if min(var)>1e-18 else None
        bands = np.zeros(4, dtype=np.float64)
        for window in fft_windows:
            power = np.abs(np.fft.rfft(window))**2
            freq = np.fft.rfftfreq(len(window), 1/file.samplerate)
            for i,(lo,hi) in enumerate(((20,120),(120,500),(500,5000),(5000,20000))):
                bands[i] += float(power[(freq>=lo)&(freq<hi)].sum())
        total = float(bands.sum())
        shares = [round(float(x/total),4) if total else 0.0 for x in bands]
        db = lambda value: round(20*math.log10(max(value,1e-12)),2)
        return {
            'duration_seconds':round(count/file.samplerate,3),
            'sample_rate':file.samplerate,'sample_count':count,
            'sample_peak_dbfs':db(peak),'rms_dbfs':db(rms),
            'crest_db':round(db(peak)-db(rms),2),
            'clipped_samples':clipped,
            'stereo_correlation':None if corr is None else round(float(np.clip(corr,-1,1)),3),
            'spectral_shares':dict(zip(('sub_bass_20_120','low_mid_120_500','mid_500_5000','high_5000_20000'),shares)),
        }


def evaluate_comparison(comparison: str | Path | dict) -> dict:
    paths,_ = load_comparison(comparison)
    result = {key:analyze_wav(paths[key]) for key in VARIANT_ORDER}
    base = result['balanced']
    differences = {key:{'rms_delta_db':round(item['rms_dbfs']-base['rms_dbfs'],2),
                        'peak_delta_db':round(item['sample_peak_dbfs']-base['sample_peak_dbfs'],2),
                        'crest_delta_db':round(item['crest_db']-base['crest_db'],2)}
                   for key,item in result.items()}
    return {'status':'ok','reference':'balanced','metrics':result,'differences':differences,
            'notes':['Sample-peak et RMS ne sont pas LUFS ni true peak.',
                     'Les pourcentages spectraux sont approximatifs; aucune victoire subjective n’est calculée.',
                     'Ces WAV sont des prémix, pas des masters certifiés streaming.']}


def local_hermes_evaluation(evaluation: dict, *, model: str='hermes3:8b',
                            base_url: str='http://127.0.0.1:11434',
                            timeout: float=90, transport=None, vision_summary=None) -> dict:
    """Advisory natural-language report. No audio files or paths ever sent to Ollama."""
    if evaluation.get('status') != 'ok': raise ValueError('Mesures audio invalides.')
    if not isinstance(model,str) or not model.strip() or len(model)>120: raise ValueError('Modèle Ollama invalide.')
    endpoint = _local_endpoint(base_url)
    system = ('Tu es un ingénieur du son prudent. Tu ne peux PAS écouter les WAV. '
              'Tu interprètes uniquement des métriques descriptives. Ne prétends jamais '
              'détecter des artefacts à l’oreille ni identifier objectivement le meilleur mix. '
              'Ne confonds pas RMS et LUFS, sample peak et true peak. '
              'Les différences peuvent provenir de simples changements de gain. '
              'Réponds exclusivement avec un objet JSON contenant exactement: '
              '{"summary":"...","observations":["..."],"recommendation":"...","caveats":["..."]}. '
              'Écris en français, bref, sans affirmer un classement acoustique certain.')
    limited = {'metrics':evaluation['metrics'],'differences':evaluation['differences']}
    if vision_summary:
        limited['spectrogram_vision_observations'] = vision_summary
        system += ' Les observations visuelles proviennent d’un modèle vision distinct; elles ne prouvent aucune qualité audible.'
    payload = {'model':model,'stream':False,'format':'json',
               'options':{'temperature':0.1},
               'messages':[{'role':'system','content':system},
                           {'role':'user','content':json.dumps(limited,ensure_ascii=False)}]}
    if transport is None:
        def transport(url,body,seconds):
            request=Request(url,data=json.dumps(body).encode('utf-8'),
                            headers={'Content-Type':'application/json'},method='POST')
            with urlopen(request,timeout=seconds) as response:
                return json.loads(response.read(512_000).decode('utf-8'))
    try:
        response=transport(endpoint,payload,timeout)
        content=response['message']['content']
        parsed=json.loads(content) if isinstance(content,str) else content
        if not isinstance(parsed,dict): raise ValueError('Objet JSON attendu.')
        output = {}
        for key in ('summary','recommendation'):
            output[key] = str(parsed.get(key,''))[:1200]
        for key in ('observations','caveats'):
            items=parsed.get(key,[])
            output[key]=[str(v)[:400] for v in items[:8]] if isinstance(items,list) else []
        return output
    except Exception as exc:
        raise AIReviewError(f'Hermes indisponible ou réponse invalide : {exc}') from exc
