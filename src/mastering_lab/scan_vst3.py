"""Inventory Windows VST3 bundles without loading untrusted plugin code."""
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DIRS = [
    Path(os.environ.get('COMMONPROGRAMFILES', r'C:\Program Files\Common Files')) / 'VST3',
    Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Common Files' / 'VST3',
    Path.home() / 'AppData' / 'Local' / 'Programs' / 'Common' / 'VST3',
]

def discover(paths: list[Path]) -> list[dict[str, str]]:
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for root in paths:
        if not root.exists():
            continue
        for item in root.rglob('*'):
            if item.suffix.lower() != '.vst3':
                continue
            key = str(item.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            results.append({'name': item.stem, 'path': str(item.resolve()), 'type': 'bundle' if item.is_dir() else 'file'})
    return sorted(results, key=lambda item: item['name'].casefold())

def main() -> None:
    parser = argparse.ArgumentParser(description='Inventory VST3 bundles (no plugin loading)')
    parser.add_argument('--dir', action='append', type=Path, dest='dirs', help='Additional VST3 directory; repeatable')
    parser.add_argument('--output', type=Path, default=Path('plugin_inventory.json'))
    args = parser.parse_args()
    dirs = DEFAULT_DIRS + (args.dirs or [])
    payload = {'generated_at': datetime.now(timezone.utc).isoformat(), 'scan_roots': [str(p) for p in dirs], 'plugins': discover(dirs)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(f"Found {len(payload['plugins'])} VST3 bundles. Saved {args.output}")
    for p in payload['plugins']:
        print(f" - {p['name']}: {p['path']}")

if __name__ == '__main__':
    main()
