"""Create/edit a per-stem configuration, then render a safe mix preview."""
from pathlib import Path
import argparse, json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mastering_lab.stem_mixer import config_template, render_mix

def main():
    p=argparse.ArgumentParser(description='Non-destructive stem mixer preview')
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--config',type=Path)
    p.add_argument('--make-config', action='store_true')
    p.add_argument('--output',type=Path)
    p.add_argument('--prepared',type=Path)
    p.add_argument('--host',type=Path, default=ROOT/'native/build/mastering-host_artefacts/Release/mastering-host.exe')
    p.add_argument('--plugin',type=Path,default=Path(r'C:\Program Files\Common Files\VST3\FabFilter\FabFilter Pro-Q 4.vst3'))
    a=p.parse_args()
    try:
        config_path=a.config or a.folder/'stem-mix.json'
        if a.make_config:
            if config_path.exists():
                raise ValueError(f'Configuration already exists: {config_path} (will not overwrite)')
            config=config_template(a.folder)
            if not config['tracks']: raise ValueError('No stems found')
            config_path.write_text(json.dumps(config,indent=2,ensure_ascii=False),encoding='utf-8')
            print(json.dumps({'status':'ok','config':str(config_path),'tracks':len(config['tracks'])}))
            return 0
        if not config_path.is_file():
            raise ValueError(f'Create config first: python scripts/stem_mix.py --folder "{a.folder}" --make-config')
        config=json.loads(config_path.read_text(encoding='utf-8'))
        output=a.output or ROOT/'sound'/'output'/'stem_mix'/a.folder.name/'stem-mix-preview.wav'
        prepared={}
        if a.prepared and a.prepared.is_file():
            from mastering_lab.fx_chain import chain_fingerprint
            data=json.loads(a.prepared.read_text(encoding='utf-8'))
            for i, track in enumerate(config['tracks']):
                chain=track.get('fx_chain', [])
                if chain and track.get('eq') and any(step.get('enabled', True) for step in chain):
                    expected=chain_fingerprint(Path(track['file']),chain)
                    info=data.get('fx_reports',{}).get(str(i),{})
                    if info.get('fingerprint') != expected:
                        raise ValueError(f'FX print is stale for {Path(track["file"]).name}. Prepare FX again before exporting.')
                    try:
                        prepared[str(i)]=data['processed'][str(i)]
                    except (KeyError, TypeError) as exc:
                        raise ValueError(f'FX print missing for {Path(track["file"]).name}. Run Prepare selected FX chains first.') from exc
        if a.prepared and not a.prepared.is_file() and any(t.get('eq') and t.get('fx_chain') for t in config.get('tracks', [])):
            raise ValueError(f'FX cache not found: {a.prepared}. Run Prepare selected FX chains first.')
        report=render_mix(a.folder,config,output,host=a.host,plugin=a.plugin,prepared=prepared)
        print(json.dumps({'status':'ok','output':report['output'],'report':str(output.with_suffix('.mix.json'))}))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'error','error':str(exc)}),file=sys.stderr)
        return 2
if __name__=='__main__':sys.exit(main())
