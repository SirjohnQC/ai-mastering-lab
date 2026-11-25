"""CLI entry point used by Stem Inspector dock (runs outside GUI process)."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mastering_lab.stem_inspector import inspect_folder, save_report, default_stem_folder


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--folder', type=Path)
    p.add_argument('--source', type=Path)
    p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args()
    folder=a.folder or default_stem_folder(a.root, a.source)
    try:
        report=inspect_folder(a.root,folder,a.source)
        dest=save_report(a.root,report,a.source)
        print(json.dumps({'status':'ok','report_path':str(dest),'stems':len(report['stems']),
                          'errors':len(report['errors']),
                          'flags':sum(len(x['suspicions']) for x in report['stems'])}))
        return 0 if report['stems'] else 3
    except Exception as exc:
        print(json.dumps({'status':'error','error':str(exc)}),file=sys.stderr)
        return 2

if __name__=='__main__':
    sys.exit(main())
