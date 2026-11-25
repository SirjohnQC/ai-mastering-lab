"""Album stem batch: render three mixes, evaluate with optional local Hermes,
and technically master the selected candidate. No VST automation or album harmonisation.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PIPELINE_ID = 'album_preferences_select_v4'


def reference_signature(path):
    path = Path(path)
    if not path.is_file():
        return 'none'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_signature(path: str | Path, kind: str) -> str:
    path = Path(path).resolve()
    if kind == 'stereo':
        sources = [path]
    elif kind == 'stems':
        sources = sorted(path.glob('*.wav'), key=lambda p: p.name.casefold())
        if len(sources) < 2:
            raise ValueError('Un dossier stems doit contenir au moins deux WAV')
    else:
        raise ValueError(f'Type audio inconnu : {kind}')
    pieces = []
    for source in sources:
        stat = source.stat()
        pieces.append((str(source.resolve()).casefold(), stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(json.dumps(pieces, ensure_ascii=False).encode('utf-8')).hexdigest()


def can_reuse_master(row: dict) -> bool:
    result = row.get('result') or {}
    if row.get('status') != 'qc_pass' or result.get('status') != 'qc_pass':
        return False
    master = result.get('file')
    if not master or not Path(master).is_file():
        return False
    saved = result.get('album_source_signature')
    if not saved:
        return False
    if row.get('kind') == 'stems':
        # Do not reuse the old dry-only v0.15.1 result as a three-candidate job.
        if result.get('album_pipeline') != PIPELINE_ID:
            return False
        # History and reference changes must refresh selection, not reuse stale masters.
        prefs_path = result.get('album_preference_history_path')
        if prefs_path and result.get('album_preference_signature') != reference_signature(prefs_path):
            return False
        # Reference library changes must refresh the Hermes mix choice.
        ref_path = result.get('album_reference_library_path')
        if ref_path and result.get('album_reference_signature') != reference_signature(ref_path):
            return False
        variants = result.get('album_candidates') or {}
        if set(variants) != {'balanced', 'vocal-focus', 'punchy'} or not all(Path(p).is_file() for p in variants.values()):
            return False
    try:
        return saved == source_signature(row['path'], row['kind'])
    except (OSError, ValueError):
        return False


def master_stem_folder(folder, output_dir, *, stop=None, progress=None,
                       render_mix_fn=None, master_fn=None, ai_decider=None, selection_fn=None, reference_path=None) -> dict:
    """Render dry A/B/C, select with bounded Hermes and master chosen candidate.

    No originals / saved stem configuration are modified. Cancellation between
    candidates is checked; the underlying mixer is not block-cancellable yet.
    """
    from .stem_mixer import config_template, render_mix
    from .auto_mix_candidates import VARIANTS
    from .album_ai_brain import choose_configs
    from .album_mix_evaluation import choose_candidate
    from .auto_master import master_song, MasteringCancelled

    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError(f'Dossier stems introuvable : {folder}')
    config = config_template(folder)
    if len(config.get('tracks', [])) < 2:
        raise ValueError('Le dossier doit contenir au moins deux stems WAV compatibles')
    for track in config['tracks']:
        track['eq'] = False
        track['fx_chain'] = []
    signature = source_signature(folder, 'stems')
    output_dir = Path(output_dir).resolve()
    target_dir = output_dir / 'premixes' / (folder.name + '-' + hashlib.sha256(str(folder).encode()).hexdigest()[:10])
    target_dir.mkdir(parents=True, exist_ok=True)
    mixes, ai_report = (ai_decider or choose_configs)(config)
    if progress:
        progress(f"{folder.name} : {'Hermes valide les gains' if ai_report.get('mode') == 'hermes' else 'variantes de secours (sans IA)'}")
    fn = render_mix_fn or render_mix
    rendered = {}
    reports = {}
    for i, name in enumerate(VARIANTS, 1):
        if stop is not None and stop.is_set():
            raise MasteringCancelled('Traitement album annulé entre les variantes.')
        if progress:
            progress(f'{folder.name} : rendu {i}/3 — {name}')
        out = target_dir / f'{name}.wav'
        reports[name] = fn(folder, mixes[name], out)
        if not out.is_file():
            raise RuntimeError(f'Mixeur : {name}.wav absent après rendu')
        rendered[name] = str(out)
    if stop is not None and stop.is_set():
        raise MasteringCancelled('Annulation demandée après les trois rendus.')
    if progress:
        progress(f'{folder.name} : évaluation DSP des 3 mixages + Hermes')
    selected, selection_report = ((selection_fn(rendered) if selection_fn else
        choose_candidate(rendered, reference_path=reference_path,
                         preferences_path=(Path(reference_path).parent / 'mix_preferences.json') if reference_path else None)))
    if selected not in VARIANTS:
        raise ValueError('Sélection hors des 3 variantes autorisées')
    if stop is not None and stop.is_set():
        raise MasteringCancelled('Annulation demandée avant le mastering.')
    if progress:
        progress(f'{folder.name} : Auto Master technique de {selected}')
    master = master_fn or master_song
    result = dict(master(Path(rendered[selected]), output_dir / 'masters', stop=stop))
    result.update({
        'album_source_signature': signature,
        'album_source': str(folder),
        'album_premix': rendered[selected],
        'album_candidates': rendered,
        'album_candidate_reports': reports,
        'album_selected_candidate': selected,
        'album_pipeline': PIPELINE_ID,
        'album_reference_library_path': str(reference_path) if reference_path else None,
        'album_reference_signature': reference_signature(reference_path) if reference_path else 'none',
        'album_preference_history_path': str(Path(reference_path).parent / 'mix_preferences.json') if reference_path else None,
        'album_preference_signature': reference_signature(Path(reference_path).parent / 'mix_preferences.json') if reference_path else 'none',
        'album_ai_decisions': ai_report,
        'album_ai_selection': selection_report,
        'album_warning': ('Les variantes utilisent des gains de groupes proposés par Hermes lorsque valides, sinon des gains de secours. Sans FX automatisés. '
                          'Hermes peut sélectionner un mix d’après RMS, crêtes et dynamique mesurés, avec secours Balanced. '
                          'Ce classement ne remplace pas une écoute ni le QC technique du master.'),
    })
    # A simple manifest so that future compare UI can load candidates without rerendering.
    manifest = target_dir / 'candidates.json'
    manifest.write_text(json.dumps({
        'schema': 1, 'pipeline': PIPELINE_ID, 'source': str(folder),
        'source_signature': signature, 'selected': selected,
        'candidates': rendered, 'reports': reports, 'ai_decisions': ai_report,
        'ai_selection': selection_report,
    }, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    result['album_candidates_manifest'] = str(manifest)
    return result
