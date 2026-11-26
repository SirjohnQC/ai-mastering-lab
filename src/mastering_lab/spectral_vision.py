"""Read-only spectrogram previews and optional local Ollama vision review.

Hermes3 is text-only; this module uses an explicitly configured vision model.
A spectrogram is not a substitute for listening or an artifact detector.
"""
from __future__ import annotations
import base64
import io
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw
from .mix_comparison import load_comparison, VARIANT_ORDER
from .ai_review import _local_endpoint, AIReviewError


def render_spectrogram(wav_path: str | Path, out_path: str | Path, *, width=640, height=256) -> Path:
    """Bounded-memory time vs log-frequency PNG, calibrated to dBFS (approximate)."""
    out_path = Path(out_path)
    canvas = spectrogram_image(wav_path, width=width, height=height)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format='PNG', optimize=True)
    return out_path


def spectrogram_image(wav_path: str | Path, *, width=640, height=256) -> Image.Image:
    fft_size = 8192
    with sf.SoundFile(str(wav_path)) as f:
        if f.frames < fft_size or f.samplerate < 32000 or f.channels < 1:
            raise ValueError('WAV trop court ou fréquence non prise en charge pour spectrogramme.')
        freq = np.fft.rfftfreq(fft_size, d=1 / f.samplerate)
        lo, hi = 40, min(18000, f.samplerate / 2 * 0.95)
        y_freqs = np.geomspace(hi, lo, height)
        indices = np.clip(np.searchsorted(freq, y_freqs), 0, len(freq)-1)
        spots = np.linspace(0, f.frames - fft_size, width, dtype=np.int64)
        arr = np.empty((height, width), np.uint8)
        win = np.hanning(fft_size)
        coherent_gain = max(1.0, win.sum())
        for col, frame in enumerate(spots):
            f.seek(int(frame))
            block = f.read(fft_size, dtype='float64', always_2d=True)
            mono = block.mean(axis=1)
            amplitude = (2 / coherent_gain) * np.abs(np.fft.rfft(mono * win))
            db = 20 * np.log10(np.maximum(amplitude[indices], 1e-8))
            arr[:, col] = np.clip((db + 100) / 85 * 255, 0, 255).astype(np.uint8)
    # Fixed palette across variants: same color always means same approximate dBFS.
    pix = arr.astype(np.float32) / 255
    rgb = np.stack((np.clip(2 * pix - .2, 0, 1),
                    np.clip(1.7 * pix - .55, 0, 1),
                    np.clip(1.4 * pix, 0, 1)), axis=-1)
    img = Image.fromarray((rgb * 255).astype(np.uint8), 'RGB')
    canvas = Image.new('RGB', (width + 78, height + 42), (15, 18, 28))
    canvas.paste(img, (67, 10))
    draw = ImageDraw.Draw(canvas)
    for hz in (60, 120, 500, 1000, 5000, 10000):
        if hz <= hi:
            y = 10 + round(height * math.log(hi/hz) / math.log(hi/lo))
            draw.text((4, y-7), f'{hz} Hz' if hz < 1000 else f'{hz//1000} kHz', fill=(205,210,220))
    draw.text((67, height + 18), '0%  |  Time across full song  |  100%', fill=(205,210,220))
    return canvas


def render_comparison_spectrograms(comparison: str | Path | dict) -> dict[str, str]:
    paths, _ = load_comparison(comparison)
    output = Path(paths['balanced']).parent / 'spectrograms'
    return {key: str(render_spectrogram(paths[key], output / f'{key}.png')) for key in VARIANT_ORDER}


def _comparison_contact_sheet(png_paths: dict[str, str]) -> bytes:
    """Combine the three spectrograms into one bounded-size image for vision LLMs."""
    # One moderately sized image is significantly cheaper than three separate images.
    from PIL import ImageOps
    canvas = Image.new('RGB', (704, 540), (15, 18, 28))
    draw = ImageDraw.Draw(canvas)
    titles = [('balanced', '1. BALANCED'), ('vocal-focus', '2. VOCAL FOCUS'),
              ('punchy', '3. PUNCHY')]
    for index, (key, title) in enumerate(titles):
        path = Path(png_paths[key])
        if path.suffix.lower() != '.png' or path.stat().st_size > 5_000_000:
            raise ValueError(f'Image PNG invalide ou trop grande : {key}')
        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as source:
            source = source.convert('RGB')
            img = ImageOps.contain(source, (680, 152), Image.Resampling.LANCZOS)
            offset = 20 + index * 178
            draw.text((12, offset), title, fill=(235, 236, 245))
            canvas.paste(img, (12, offset+18))
    out = io.BytesIO()
    canvas.save(out, 'PNG', optimize=True)
    return out.getvalue()


def _parse_vision_content(answer: str) -> dict:
    """Only parse the answer channel. Reasoning/thinking is NOT an observation."""
    answer = answer.strip()
    candidate = answer
    if candidate.startswith('```'):
        candidate = candidate.split('\n', 1)[-1]
        if candidate.rstrip().endswith('```'):
            candidate = candidate.rstrip()[:-3].strip()
    try:
        parsed = json.loads(candidate)
    except ValueError:
        return {'observations': ['Réponse visuelle non structurée : ' + answer[:1200]],
                'limits': ['À confirmer avec les mesures DSP et une écoute humaine.']}
    if not isinstance(parsed, dict):
        raise AIReviewError('Réponse JSON vision invalide (objet attendu).')
    return {field: [str(v)[:500] for v in parsed.get(field, [])[:8]]
            if isinstance(parsed.get(field), list) else [] for field in ('observations', 'limits')}


def local_vision_review(png_paths: dict[str, str], *, model='qwen3-vl:4b',
                        base_url='http://127.0.0.1:11434', timeout=150, transport=None) -> dict:
    """One compact comparison PNG; bounded response; no retry loop or bogus audio claims."""
    prompt = (
        'Voici 3 spectrogrammes superposés: Balanced, Vocal Focus, Punchy. '
        'Échelles identiques. En français, donne 2 différences VISUELLES observables, '
        'en 60 mots maximum. Si aucune différence visible: dis-le. '
        'Ne prétends pas avoir écouté le son. Pas de raisonnement, pas de JSON.'
    )
    return _review_image(_comparison_contact_sheet(png_paths), prompt,
                         model=model, base_url=base_url, timeout=timeout, transport=transport)


def review_vocal_whistles(path, markers, *, model):
    image = spectrogram_image(path)
    with io.BytesIO() as output:
        image.save(output, format='PNG')
        png = output.getvalue()
    measured = ', '.join(
        f"{m['start']:.1f}–{m['end']:.1f} s à {m['hz']:.0f} Hz" for m in markers
    ) or 'aucune crête stable détectée'
    prompt = (
        "Voici le spectrogramme d’une piste vocale. Les repères issus de la FFT "
        f"sont : {measured}. En français, indique en deux phrases si des traits "
        "horizontaux étroits sont visibles et ce qui pourrait être une harmonique normale. "
        "Si la résolution est insuffisante, dis-le. Ne prétends pas avoir écouté "
        "ni identifié l’origine IA du son. Réponds avec un objet JSON contenant "
        "une liste observations et une liste limits."
    )
    return _review_image(png, prompt, model=model, base_url='http://127.0.0.1:11434',
                         timeout=45, transport=None)


def _review_image(png, prompt, *, model, base_url, timeout, transport):
    if not isinstance(model, str) or not model.strip() or len(model) > 120:
        raise ValueError('Modèle de vision Ollama invalide.')
    endpoint = _local_endpoint(base_url)
    img = base64.b64encode(png).decode('ascii')
    payload = {'model': model, 'stream': False, 'think': False,
               'options': {'temperature': 0, 'num_predict': 3072},
               'messages': [{'role':'user','content':prompt,'images':[img]}]}
    if transport is None:
        def transport(url, body, seconds):
            req = Request(url, data=json.dumps(body).encode('utf-8'),
                          headers={'Content-Type':'application/json'}, method='POST')
            try:
                with urlopen(req, timeout=seconds) as resp:
                    raw = resp.read(4_000_000)
            except HTTPError as exc:
                detail = exc.read(2500).decode('utf-8', errors='replace')
                raise AIReviewError(f'Ollama HTTP {exc.code}: {detail or exc.reason}') from exc
            except (URLError, TimeoutError) as exc:
                raise AIReviewError(f'Connexion ou délai Ollama : {exc}') from exc
            if not raw.strip():
                raise AIReviewError('Ollama a retourné une réponse HTTP vide.')
            try:
                return json.loads(raw.decode('utf-8'))
            except (UnicodeError, ValueError) as exc:
                excerpt = raw.decode('utf-8', errors='replace')[:450]
                raise AIReviewError(f'Réponse HTTP Ollama non JSON : {excerpt!r}') from exc
    try:
        response = transport(endpoint, payload, timeout)
        if not isinstance(response, dict):
            raise AIReviewError('Ollama a retourné un objet inattendu.')
        if response.get('error'):
            raise AIReviewError(f"Erreur Ollama : {str(response['error'])[:600]}")
        message = response.get('message') or {}
        answer = message.get('content') if isinstance(message, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            reason = response.get('done_reason', 'inconnu')
            if reason == 'length':
                raise AIReviewError('Qwen a épuisé son budget de 3072 tokens '
                                    'dans le raisonnement interne avant de répondre. '
                                    'Vision ignorée; mesures DSP et Hermes préservés. '
                                    'Sélectionner un modèle vision sans thinking dans Settings.')
            raise AIReviewError(f'Réponse vision vide (done_reason={reason}). '
                                'Mesures DSP et Hermes préservés.')
        return _parse_vision_content(answer)
    except AIReviewError:
        raise
    except Exception as exc:
        raise AIReviewError(f'Vision Ollama indisponible ({type(exc).__name__}) : {exc}') from exc
