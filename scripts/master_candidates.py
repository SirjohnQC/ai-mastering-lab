"""Batch reference-guided Pro-Q4 candidates. Default: plan only; --render: render WAVs."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from mastering_lab.reference import analyze
from mastering_lab.candidates import plan_candidates, measure_candidate, shape_distance
from mastering_lab.proq4 import build_changes
from mastering_lab.host import run_host
from reference_eq import discover, decode_for_processing, safe_stem


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Generate Warm / Balanced / Punchy reference EQ candidates')
    p.add_argument('--sound-dir', type=Path, default=ROOT/'sound')
    p.add_argument('--source', type=Path)
    p.add_argument('--reference', type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--render', action='store_true', help='Render the candidate WAVs through Pro-Q 4')
    p.add_argument('--strength', type=float, default=.55)
    p.add_argument('--max-gain', type=float, default=2.)
    p.add_argument('--host', type=Path, default=ROOT/'native/build/mastering-host_artefacts/Release/mastering-host.exe')
    p.add_argument('--plugin', type=Path, default=Path(r'C:\Program Files\Common Files\VST3\FabFilter\FabFilter Pro-Q 4.vst3'))
    args = p.parse_args(argv)
    try:
        sources, ref = discover(args.sound_dir, args.source, args.reference)
        if not 0 < args.strength <= 1 or not 0 < args.max_gain <= 6:
            raise ValueError('strength must be >0 to 1 and max-gain >0 to 6 dB')
        if args.render and (not args.host.is_file() or not args.plugin.exists()):
            raise ValueError(f'Host or plugin missing: {args.host} / {args.plugin}')
    except ValueError as e:
        p.error(str(e))

    destination = args.out or args.sound_dir/'output'/'candidates'
    destination.mkdir(parents=True, exist_ok=True)
    errors = 0
    inspect_data = None
    with tempfile.TemporaryDirectory(prefix='aml-candidates-') as temp:
        tmp = Path(temp)
        try:
            ref_wav = decode_for_processing(ref, tmp, 'reference')
            ref_stats = analyze(ref_wav)
        except Exception as e:
            p.error(f'Cannot analyze reference: {e}')
        for i, source in enumerate(sources, 1):
            print(f'[{i}/{len(sources)}] {source.name}', flush=True)
            try:
                source_wav = decode_for_processing(source, tmp, f'source-{i}')
                original = analyze(source_wav)
                plans = plan_candidates(original, ref_stats, strength=args.strength,
                                        max_gain_db=args.max_gain)
                # Disambiguate song.mp3 and song.wav (same stem) and unsafe chars.
                stem = safe_stem(source.stem)
                if sum(safe_stem(s.stem).casefold() == stem.casefold() for s in sources) > 1:
                    stem += '-' + source.suffix[1:].lower()
                song_dir = destination/stem
                song_dir.mkdir(parents=True, exist_ok=True)
                payload = {
                    'source': str(source), 'reference': str(ref),
                    'original': original.__dict__,
                    'original_spectral_distance_to_reference_db': shape_distance(original, ref_stats),
                    'candidate_profiles': {},
                    'note': 'These are EQ-only proposals, not final Spotify masters. Compare level-matched.'
                }
                for name, suggestions in plans.items():
                    candidate = {'eq_plan': suggestions, 'status': 'planned'}
                    if args.render:
                        if inspect_data is None:
                            inspect_data = run_host(args.host, 'inspect', plugin=args.plugin)
                        changes = build_changes(inspect_data, suggestions)
                        output = song_dir/f'{stem}-{name}.wav'
                        state_out = song_dir/f'{stem}-{name}.proq4.state'
                        if changes:
                            result = run_host(args.host, 'render', plugin=args.plugin,
                                              input_file=source_wav, output_file=output,
                                              parameter_changes=changes, state_out=state_out,
                                              timeout=600)
                            if not output.exists() or output.stat().st_size < 44:
                                raise RuntimeError(f'Host returned success but output WAV missing/empty: {output}')
                            candidate.update({'status':'rendered','wav':str(output),
                                              'plugin_state':str(state_out),
                                              'parameter_readback': result.get('parameter_changes', []),
                                              'metrics':measure_candidate(output, original, ref_stats)})
                            print(f'  {name}: {output.name} | spectral Δ {candidate["metrics"]["spectral_distance_change_db"]:+.2f} dB')
                        else:
                            candidate['status'] = 'no_eq_changes'
                            candidate['note'] = 'No EQ corrections above threshold: unchanged original is baseline.'
                    else:
                        print(f'  {name}: {sum(abs(s["recommended_gain_db"])>=.35 for s in suggestions)} proposed bands')
                    payload['candidate_profiles'][name] = candidate
                report_path = song_dir/'candidate-report.json'
                report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
                print(f'  Report: {report_path}')
            except Exception as e:
                errors += 1
                print(f'  ERROR: {e}', file=sys.stderr)
    print(f'Done. {len(sources)-errors}/{len(sources)} songs processed. {destination}')
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
