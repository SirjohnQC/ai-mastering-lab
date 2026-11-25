"""Reference-guided EQ with WAV and MP3 auto-discovery.

MP3 is decoded to a temporary PCM WAV through FFmpeg. Originals are untouched.
"""
from __future__ import annotations

import argparse
import re
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mastering_lab.reference import report, save_report
from mastering_lab.proq4 import build_changes
from mastering_lab.host import run_host


AUDIO_SUFFIXES = frozenset({'.wav', '.mp3'})


def audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise ValueError(f'Missing folder: {folder}')
    return sorted((p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES),
                  key=lambda p: p.name.casefold())


def discover(sound: Path, source: Path | None, reference: Path | None) -> tuple[list[Path], Path]:
    if source is not None:
        if not source.is_file() or source.suffix.lower() not in AUDIO_SUFFIXES:
            raise ValueError(f'Source must be an existing WAV or MP3: {source}')
        sources = [source]
    else:
        sources = audio_files(sound / 'source')
        if not sources:
            raise ValueError(f'No WAV or MP3 files in {sound / "source"}')
    if reference is not None:
        if not reference.is_file() or reference.suffix.lower() not in AUDIO_SUFFIXES:
            raise ValueError(f'Reference must be an existing WAV or MP3: {reference}')
        ref = reference
    else:
        options = audio_files(sound / 'ref')
        if not options:
            raise ValueError(f'No WAV or MP3 reference in {sound / "ref"}')
        if len(options) > 1:
            raise ValueError('Multiple reference files found in sound/ref. Keep just one, or use --reference PATH.\n' + '\n'.join(map(str, options)))
        ref = options[0]
    for p in sources:
        if p.resolve() == ref.resolve():
            raise ValueError('Source and reference must be different files')
    return sources, ref


def decode_for_processing(path: Path, temporary_dir: Path, key: str) -> Path:
    """Convert only MP3s, leaving original WAVs and all source files untouched."""
    if path.suffix.lower() == '.wav':
        return path
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('MP3 support requires FFmpeg on PATH. Install using: winget install Gyan.FFmpeg')
    output = temporary_dir / f'{key}.wav'
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-i', str(path), '-map', '0:a:0', '-vn', '-ac', '2',
               '-c:a', 'pcm_f32le', str(output)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 44:
        raise RuntimeError(f'Could not decode MP3 {path}: {result.stderr.strip()}')
    return output

def safe_stem(name: str) -> str:
    stem = re.sub(r'[^\w. -]+', '_', name, flags=re.UNICODE).strip(' .')
    return stem or 'track'


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Analyze WAV/MP3 source tracks against one WAV/MP3 reference.')
    p.add_argument('--sound-dir', type=Path, default=ROOT / 'sound', help='Folder containing source/ and ref/')
    p.add_argument('--source', type=Path, help='Optional WAV/MP3 source (default: all sound/source/*.{wav,mp3})')
    p.add_argument('--reference', type=Path, help='Optional WAV/MP3 reference (default: unique audio file in sound/ref/)')
    p.add_argument('--out', type=Path, help='Output folder for reports and renders (default: sound/output)')
    p.add_argument('--strength', type=float, default=.55)
    p.add_argument('--max-gain', type=float, default=2.)
    p.add_argument('--render', action='store_true', help='Apply proposed EQ with installed Pro-Q 4')
    p.add_argument('--host', type=Path, default=ROOT / 'native/build/mastering-host_artefacts/Release/mastering-host.exe')
    p.add_argument('--plugin', type=Path, default=Path(r'C:\Program Files\Common Files\VST3\FabFilter\FabFilter Pro-Q 4.vst3'))
    args = p.parse_args(argv)
    out_dir = args.out or args.sound_dir / 'output'
    try:
        sources, ref = discover(args.sound_dir, args.source, args.reference)
    except ValueError as exc:
        p.error(str(exc))
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f'Reference: {ref}')
    print(f'Source audio files: {len(sources)}')
    if args.render and (not args.host.is_file() or not args.plugin.exists()):
        p.error(f'Cannot render: check host ({args.host}) and plugin ({args.plugin})')
    inspect = None
    failures = 0
    with tempfile.TemporaryDirectory(prefix='mastering-lab-') as tmp:
        tempdir = Path(tmp)
        # Decode the reference only once for the whole batch.
        try:
            ref_wav = decode_for_processing(ref, tempdir, 'reference')
        except Exception as exc:
            p.error(str(exc))
        for i, src in enumerate(sources, start=1):
            print(f'\n[{i}/{len(sources)}] {src.name}', flush=True)
            stem = safe_stem(src.stem)
            # Include the extension when two sources share a name, e.g. song.mp3/song.wav.
            ambiguous = sum(safe_stem(other.stem).casefold() == stem.casefold() for other in sources) > 1
            if ambiguous:
                import hashlib
                stem += '-' + hashlib.sha256(src.name.encode('utf-8')).hexdigest()[:8]
            report_path = out_dir / f'{stem}.json'
            output_path = out_dir / f'{stem}-eq.wav'
            try:
                src_wav = decode_for_processing(src, tempdir, f'source-{i}')
                analysis = report(src_wav, ref_wav, args.strength, args.max_gain)
                # Reports should identify the original files, not the temporary WAV paths.
                analysis['source']['file'] = str(src)
                analysis['reference']['file'] = str(ref)
                save_report(analysis, report_path)
                print(f'Report: {report_path}')
                for row in analysis['suggestions']:
                    print(f"  {row['center_hz']:>6.0f} Hz: {row['recommended_gain_db']:+.2f} dB")
                if args.render:
                    if inspect is None:
                        inspect = run_host(args.host, 'inspect', plugin=args.plugin)
                    changes = build_changes(inspect, analysis['suggestions'])
                    if not changes:
                        print('No meaningful changes; skipped render.')
                        continue
                    payload = run_host(args.host, 'render', plugin=args.plugin, input_file=src_wav,
                                       output_file=output_path, parameter_changes=changes,
                                       state_out=out_dir / f'{stem}.proq4.state')
                    print(f'Rendered: {output_path}')
                    for change in payload.get('parameter_changes', []):
                        if abs(change.get('actual', -99) - change.get('requested', -999)) > .015:
                            print(f'WARNING: parameter readback differs: {change}')
            except Exception as exc:
                failures += 1
                print(f'ERROR processing {src.name}: {exc}', file=sys.stderr)
    print(f'\nCompleted: {len(sources)-failures}/{len(sources)} source tracks processed. Output folder: {out_dir}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
