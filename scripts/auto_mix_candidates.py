"""Generate 3 real WAV candidate mixes with existing FX prints (if enabled)."""
from __future__ import annotations
from pathlib import Path
import argparse, json, subprocess, sys, tempfile, uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mastering_lab.auto_mix_candidates import candidate_configs

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--prepared',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:
        config=json.loads(args.config.read_text(encoding='utf-8'))
        variants=candidate_configs(config)
        args.out.mkdir(parents=True,exist_ok=True)
        # Never overwrite an old comparison or the user's existing project configuration.
        session=args.out/('session-'+uuid.uuid4().hex[:10])
        session.mkdir()
        outputs={}
        with tempfile.TemporaryDirectory(prefix='aml-variants-') as td:
            for label,variant in variants.items():
                config_tmp=Path(td)/f'{label}.json'
                config_tmp.write_text(json.dumps(variant,ensure_ascii=False,indent=2),encoding='utf-8')
                dest=session/f'{label}.wav'
                cmd=[sys.executable,str(ROOT/'scripts'/'stem_mix.py'),'--folder',str(args.folder),
                     '--config',str(config_tmp),'--output',str(dest),'--prepared',str(args.prepared)]
                result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=900)
                if result.returncode or not dest.is_file():
                    lines=(result.stderr+'\n'+result.stdout).strip().splitlines()
                    raise RuntimeError(f'{label}: '+ '\n'.join(lines[-4:])[-1000:])
                report=json.loads(dest.with_suffix('.mix.json').read_text(encoding='utf-8'))
                outputs[label]={'wav':str(dest.resolve()),'mix_report':str(dest.with_suffix('.mix.json')),
                                'pre_safety_peak_dbfs':report.get('pre_safety_peak_dbfs'),
                                'global_safety_gain_db':report.get('global_safety_gain_db')}
                print(f'Variante {label} rendue : {dest.name}',file=sys.stderr,flush=True)
        report={'status':'ok','folder':str(session.resolve()),'variants':outputs,
                'source':{'config':str(args.config.resolve()),'folder':str(args.folder.resolve()),'prepared':str(args.prepared.resolve())},
                'warning':'Ce sont des variantes de gain prudentes, pas des masters, ni des choix validés par écoute IA.'}
        (session/'comparison.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False));return 0
    except Exception as exc:
        print(json.dumps({'status':'error','error':str(exc)},ensure_ascii=False));return 2
if __name__=='__main__':sys.exit(main())
