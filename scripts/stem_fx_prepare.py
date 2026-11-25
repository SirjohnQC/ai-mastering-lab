"""Render only enabled FX chains, preserving originals and writing an indexed preview cache."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mastering_lab.fx_chain import prepare_chain, chain_fingerprint
from mastering_lab.stem_mixer import parse_tracks


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--host', type=Path, default=ROOT/'native/build/mastering-host_artefacts/Release/mastering-host.exe')
    args = p.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding='utf-8'))
        tracks = parse_tracks(config, args.folder)
        args.out.mkdir(parents=True, exist_ok=True)
        processed = {}
        reports = {}
        for i, track in enumerate(tracks):
            chain = config['tracks'][i].get('fx_chain', [])
            if not any(s.get('enabled', True) for s in chain):
                continue
            fingerprint = chain_fingerprint(track.path, chain)
            dest = args.out / f'{i:02d}-{fingerprint}-fx.wav'
            if dest.is_file():
                with __import__('soundfile').SoundFile(dest):
                    pass
                reports[str(i)] = {'status':'cached', 'output':str(dest)}
            else:
                reports[str(i)] = prepare_chain(track.path, chain, dest, args.host)
            reports[str(i)]['fingerprint'] = fingerprint
            processed[str(i)] = str(dest.resolve())
            print(f'FX prepared: {track.path.name}', file=sys.stderr, flush=True)
        result = {'status':'ok', 'processed':processed, 'fx_reports':reports}
        staging = args.out/'prepared.json.tmp'
        staging.write_text(json.dumps(result, indent=2), encoding='utf-8')
        staging.replace(args.out/'prepared.json')
        print(json.dumps(result));return 0
    except Exception as e:
        print(json.dumps({'status':'error','error':str(e)}));return 2
if __name__ == '__main__': sys.exit(main())
