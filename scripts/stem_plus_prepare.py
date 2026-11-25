"""Prepare optional offline Pro-Q 4 tracks. Originals are never modified."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mastering_lab.stem_mixer import parse_tracks, _eq_stem, PRESETS

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--host',type=Path,default=ROOT/'native/build/mastering-host_artefacts/Release/mastering-host.exe')
    p.add_argument('--plugin',type=Path,default=Path(r'C:\Program Files\Common Files\VST3\FabFilter\FabFilter Pro-Q 4.vst3'))
    a=p.parse_args()
    try:
        config=json.loads(a.config.read_text(encoding='utf-8'))
        tracks=parse_tracks(config,a.folder)
        a.out.mkdir(parents=True,exist_ok=True)
        processed={}
        for i,t in enumerate(tracks):
            if not t.eq:continue
            category=config['tracks'][i].get('category','other')
            if not PRESETS.get(category,[]):
                print(f'Skipping {t.path.name}: no EQ preset for {category}',file=sys.stderr,flush=True)
                continue
            # Pro-Q offline renderer currently supports WAV only.
            if t.path.suffix.lower()!='.wav':
                raise ValueError(f'{t.path.name}: convert MP3 stems to WAV before preparing EQ')
            target=a.out/f'{i:02d}-{t.path.stem}-proq.wav'
            data=_eq_stem(t.path,target,a.host,a.plugin,category)
            if not target.is_file():
                raise RuntimeError(f'No output for {t.path.name}; no valid EQ bands perhaps')
            processed[str(i)]=str(target.resolve())
            print(f'Prepared {t.path.name}',file=sys.stderr,flush=True)
        result={'status':'ok','processed':processed}
        (a.out/'prepared.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result));return 0
    except Exception as e:
        print(json.dumps({'status':'error','error':str(e)}));return 2
if __name__=='__main__':sys.exit(main())
