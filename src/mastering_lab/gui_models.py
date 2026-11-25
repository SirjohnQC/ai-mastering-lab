"""UI-independent file/report handling for AI Mastering Lab desktop application."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

SUPPORTED = frozenset({'.wav', '.mp3'})
PROFILES = ('original', 'balanced', 'warm', 'punchy')


def list_audio(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED), key=lambda p:p.name.casefold())


def find_report(root: Path, source: Path) -> Path | None:
    """Prefer exact report source matching (handles collisions between WAV and MP3)."""
    base = root / 'sound' / 'output' / 'candidates'
    if not base.exists():
        return None
    for path in base.glob('*/candidate-report.json'):
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
            if Path(report['source']).resolve() == source.resolve():
                return path
        except (ValueError, KeyError, OSError, TypeError):
            continue
    return None


def audio_choices(report: dict, source: Path) -> dict[str, Path]:
    result = {'original': source}
    for name in PROFILES[1:]:
        entry = report.get('candidate_profiles', {}).get(name, {})
        wav = entry.get('wav')
        if entry.get('status') == 'rendered' and wav and Path(wav).is_file():
            result[name] = Path(wav)
    return result


def audition_gain(report: dict, name: str) -> float:
    """Linear amplitude correction using measured full-track RMS, capped to avoid boosts.

    Not instantaneous loudness matching, not LUFS. Baseline is the quietest
    available rendered candidate/original so we only attenuate.
    """
    levels = {'original': report.get('original', {}).get('rms_dbfs')}
    for profile, entry in report.get('candidate_profiles', {}).items():
        if entry.get('status') == 'rendered':
            levels[profile] = entry.get('metrics', {}).get('analysis', {}).get('rms_dbfs')
    levels = {k:float(v) for k,v in levels.items() if isinstance(v,(float,int))}
    if name not in levels or not levels:
        return 1.0
    quietest = min(levels.values())
    return max(.01, min(1., 10 ** ((quietest-levels[name])/20)))


def store_preference(path: Path, source: Path, reference: Path, profile: str) -> None:
    if profile not in PROFILES:
        raise ValueError('Unknown profile')
    path.parent.mkdir(parents=True, exist_ok=True)
    entries=[]
    if path.is_file():
        try:
            old=json.loads(path.read_text(encoding='utf-8'))
            if isinstance(old,list):entries=old
        except (OSError, ValueError):
            entries=[]
    entries.append({'source':str(source.resolve()),'reference':str(reference.resolve()),
                    'selected':profile,'timestamp_utc':datetime.now(timezone.utc).isoformat()})
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)
