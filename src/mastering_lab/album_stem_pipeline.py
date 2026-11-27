"""Album stem batch: render three mixes, evaluate with optional local Hermes,
and technically master the selected candidate, with optional corrective EQ.
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


def can_reuse_master(row: dict, *, external_reference_wav=None, corrective_eq=False, auto_cleanup=False) -> bool:
    result = row.get('result') or {}
    if row.get('status') != 'qc_pass' or result.get('status') != 'qc_pass':
        return False
    if result.get('album_auto_cleanup_enabled', False) != auto_cleanup:
        return False
    if bool(result.get('album_corrective_eq')) != bool(corrective_eq):
        return False
    master = result.get('file')
    if not master or not Path(master).is_file():
        return False
    saved = result.get('album_source_signature')
    if not saved:
        return False
    if row.get('kind') == 'stems':
        from .stem_saturation import selection_signature
        saved_sat=result.get('album_stem_saturation_signature','none')
        requested_sat=selection_signature(row.get('stem_saturation'))
        if (result.get('album_stem_de_sizzle') or {}) != (row.get('stem_de_sizzle') or {}):
            return False
        if saved_sat!=requested_sat:
            return False
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
        # The user's standalone reference is part of the premix decision.
        # Changing or removing it must invalidate previously chosen stem mixes.
        external_path = result.get('album_external_reference_path')
        selected = str(Path(external_reference_wav).resolve()) if external_reference_wav else None
        if (str(Path(external_path).resolve()) if external_path else None) != selected:
            return False
        if external_path:
            try:
                if result.get('album_external_reference_signature') != source_signature(external_path, 'stereo'):
                    return False
            except (OSError, ValueError):
                return False
        variants = result.get('album_candidates') or {}
        if set(variants) != {'balanced', 'vocal-focus', 'punchy'} or not all(Path(p).is_file() for p in variants.values()):
            return False
    try:
        return saved == source_signature(row['path'], row['kind'])
    except (OSError, ValueError):
        return False


def master_album_with_eq(source, output_dir, *, root, plugin, reference_path=None,
                         stop=None, progress=None):
    """Apply the opt-in, bounded EQ before measuring and mastering the result."""
    from .auto_master import master_song, MasteringCancelled
    from .ai_fx_intelligence import propose_for_wav, render_approved_eq

    def check_cancelled():
        if stop is not None and stop.is_set():
            raise MasteringCancelled('EQ album annulé.')

    def notify(message):
        check_cancelled()
        if progress:
            progress(message)

    notify('Hermes · analyse EQ de ' + Path(source).stem)
    plan = propose_for_wav(source, reference_path=reference_path,
                           eq_preferences_path=Path(root) / 'settings/eq_preferences.json')
    check_cancelled()
    eq = {'status': 'no_change', 'summary': plan['summary'], 'moves': []}
    mastering_input = source
    if plan['moves']:
        eq = render_approved_eq(source, plan, root=root, plugin=plugin, progress=notify)
        mastering_input = eq['after']
    check_cancelled()
    result = master_song(mastering_input, output_dir, stop=stop)
    result['album_corrective_eq'] = eq
    sidecar = Path(result['file']).with_suffix('.qc.json')
    temporary = sidecar.with_suffix('.json.tmp')
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(sidecar)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def master_album_stereo(source, output_dir, *, master, stop=None, progress=None,
                        auto_cleanup=False):
    source = Path(source).resolve()
    signature = source_signature(source, 'stereo')
    applied = {}
    mastering_input = source
    if auto_cleanup:
        from .de_sizzle import auto_sizzle_passages, prepare_de_sizzle

        if progress:
            progress('Analyse des aigus · ' + source.stem)
        passages = auto_sizzle_passages(source, stop=stop)
        if passages:
            applied = {str(source): passages}
            if progress:
                progress('Correction des aigus · ' + source.stem)
            folder = Path(output_dir) / 'premixes' / ('stereo-' + signature[:16])
            folder.mkdir(parents=True, exist_ok=True)
            prepared = {}
            prepare_de_sizzle({'tracks': [{'file': str(source)}]}, applied, prepared, folder, stop=stop)
            mastering_input = prepared['0']
    if progress:
        progress('Mastering · ' + source.stem)
    result = dict(master(mastering_input, output_dir, stop=stop))
    result.update(album_source_signature=signature, album_auto_cleanup_enabled=auto_cleanup,
                  album_auto_de_sizzle=applied)
    return result


def master_stem_folder(folder, output_dir, *, stop=None, progress=None,
                       render_mix_fn=None, master_fn=None, ai_decider=None, selection_fn=None, reference_path=None, external_reference_wav=None, stem_saturation=None, de_sizzle=None, auto_cleanup=False) -> dict:
    """Render dry A/B/C, select with bounded Hermes and master chosen candidate.

    No originals / saved stem configuration are modified. Cancellation between
    candidates is checked; the underlying mixer is not block-cancellable yet.
    """
    from .stem_mixer import config_template, render_mix
    from .auto_mix_candidates import VARIANTS
    from .album_ai_brain import choose_configs
    from .album_mix_evaluation import choose_candidate
    from .auto_master import master_song, MasteringCancelled
    from .stem_saturation import (
        validated_selections, selection_signature, prepare_selected_stems
    )

    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError(f'Dossier stems introuvable : {folder}')
    config = config_template(folder)
    if len(config.get('tracks', [])) < 2:
        raise ValueError('Le dossier doit contenir au moins deux stems WAV compatibles')
    for track in config['tracks']:
        track['eq'] = False
        track['fx_chain'] = []
    automatic = {}
    if auto_cleanup:
        from .de_sizzle import auto_stem_sizzle

        automatic = auto_stem_sizzle(config, de_sizzle or {}, stop=stop, progress=progress)
    repairs = {**automatic, **(de_sizzle or {})}
    if progress:
        progress(f'{folder.name} : préparation des corrections')
    saturation_settings=validated_selections(config,stem_saturation)
    saturation_signature=selection_signature(saturation_settings)
    signature = source_signature(folder, 'stems')
    output_dir = Path(output_dir).resolve()
    target_dir = output_dir / 'premixes' / (folder.name + '-' + hashlib.sha256(str(folder).encode()).hexdigest()[:10])
    target_dir.mkdir(parents=True, exist_ok=True)
    prepared, saturation_report=prepare_selected_stems(
        config,saturation_settings,target_dir/'saturated_stems',stop=stop
    )
    if repairs:
        from .de_sizzle import prepare_de_sizzle

        prepare_de_sizzle(config, repairs, prepared, target_dir, stop=stop)
    # The prepared, original-length wet prints enter the normal mixer before
    # group gain decisions and before technical mastering. All three variants
    # use the same user-approved selection, with no source-stem modification.
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
        mix_config=mixes[name]
        if prepared:
            for key in prepared:
                track = mix_config['tracks'][int(key)]
                track['eq'] = True
                track['fx_chain'] = []
                if track['file'] in (saturation_settings or {}):
                    track['fx_chain'].append({'kind': 'approved_stem_saturation'})
                if track['file'] in (de_sizzle or {}):
                    track['fx_chain'].append({'kind': 'approved_de_sizzle'})
                elif track['file'] in automatic:
                    track['fx_chain'].append({'kind': 'automatic_de_sizzle'})
        if render_mix_fn is None:
            reports[name]=fn(folder,mix_config,out,prepared=prepared)
        else:
            # Compatibility with test renderer injection: no kwarg when
            # there is no approved stem saturation.
            reports[name]=fn(folder,mix_config,out,prepared=prepared) if prepared else fn(folder,mix_config,out)
        if not out.is_file():
            raise RuntimeError(f'Mixeur : {name}.wav absent après rendu')
        rendered[name] = str(out)
    if stop is not None and stop.is_set():
        raise MasteringCancelled('Annulation demandée après les trois rendus.')
    if progress:
        progress(f'{folder.name} : évaluation DSP des 3 mixages + Hermes')
    selected, selection_report = ((selection_fn(rendered) if selection_fn else
        choose_candidate(rendered, reference_path=reference_path,
                         external_reference_wav=external_reference_wav,
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
        'album_stem_saturation_signature':saturation_signature,
        'album_stem_saturation':saturation_report,
        'album_stem_de_sizzle': de_sizzle or {},
        'album_auto_cleanup_enabled': auto_cleanup,
        'album_auto_de_sizzle': automatic,
        'album_external_reference_path': str(external_reference_wav) if external_reference_wav else None,
        'album_external_reference_signature': source_signature(external_reference_wav, 'stereo') if external_reference_wav else None,
        'album_reference_library_path': str(reference_path) if reference_path else None,
        'album_reference_signature': reference_signature(reference_path) if reference_path else 'none',
        'album_preference_history_path': str(Path(reference_path).parent / 'mix_preferences.json') if reference_path else None,
        'album_preference_signature': reference_signature(Path(reference_path).parent / 'mix_preferences.json') if reference_path else 'none',
        'album_ai_decisions': ai_report,
        'album_ai_selection': selection_report,
        'album_warning': ('Les variantes utilisent des gains de groupes proposés par Hermes lorsque valides, sinon des gains de secours. Saturation des stems uniquement avec approbation explicite. '
                          'Hermes peut sélectionner un mix d’après RMS, crêtes et dynamique mesurés, avec secours Balanced. '
                          'Ce classement ne remplace pas une écoute ni le QC technique du master.'),
    })
    # A simple manifest so that future compare UI can load candidates without rerendering.
    manifest = target_dir / 'candidates.json'
    manifest.write_text(json.dumps({
        'schema': 1, 'pipeline': PIPELINE_ID, 'source': str(folder),
        'source_signature': signature, 'selected': selected,
        'candidates': rendered, 'reports': reports, 'ai_decisions': ai_report,
        'stem_saturation':saturation_report,
        'stem_de_sizzle': de_sizzle or {},
        'auto_de_sizzle': automatic,
        'ai_selection': selection_report,
    }, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    result['album_candidates_manifest'] = str(manifest)
    return result
