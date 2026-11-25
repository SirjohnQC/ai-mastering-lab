import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mastering_lab.album_stem_pipeline import source_signature, can_reuse_master, master_stem_folder

class AlbumStemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'a song' / 'stems'
        self.folder.mkdir(parents=True)
        import numpy as np
        import soundfile as sf
        for name, hz in [('Lead Vocals', 260), ('Drums', 90)]:
            t=np.arange(4800)/48000
            sf.write(self.folder/(name+'.wav'), 0.05*np.sin(2*np.pi*hz*t), 48000)
    def tearDown(self): self.tmp.cleanup()
    def test_signature_stable_and_changes(self):
        first=source_signature(self.folder, 'stems')
        self.assertEqual(first,source_signature(self.folder,'stems'))
        (self.folder / 'Drums.wav').write_bytes((self.folder/'Drums.wav').read_bytes()+b'X')
        self.assertNotEqual(first,source_signature(self.folder,'stems'))
    def test_reuse_requires_fingerprint(self):
        outfile=self.root/'master.wav';outfile.write_bytes(b'test')
        row={'kind':'stems','path':str(self.folder),'status':'qc_pass','result':{'status':'qc_pass','file':str(outfile)}}
        self.assertFalse(can_reuse_master(row))
        row['result']['album_source_signature']=source_signature(self.folder,'stems')
        self.assertTrue(can_reuse_master(row))
    def test_render_to_master_and_preserve_files(self):
        original={p.name:p.read_bytes() for p in self.folder.glob('*.wav')}
        def fake_mix(folder, config, output):
            self.assertEqual(len(config['tracks']),2)
            self.assertTrue(all(not t.get('eq') and not t.get('fx_chain') for t in config['tracks']))
            output.write_bytes(b'premix')
            return {'status':'ok','output':str(output)}
        def fake_master(source,outdir,*,stop):
            self.assertEqual(source.read_bytes(),b'premix')
            outfile=outdir/'test-master.wav';outfile.parent.mkdir(exist_ok=True,parents=True);outfile.write_bytes(b'master')
            return {'status':'qc_pass','file':str(outfile)}
        result=master_stem_folder(self.folder,self.root/'output',render_mix_fn=fake_mix,master_fn=fake_master)
        self.assertEqual(result['status'],'qc_pass')
        self.assertEqual(result['album_pipeline'],'dry_stems_to_stereo_then_technical_master')
        self.assertTrue(can_reuse_master({'kind':'stems','path':str(self.folder),'status':'qc_pass','result':result}))
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.glob('*.wav')},original)
    def test_missing_folder(self):
        with self.assertRaises(ValueError): master_stem_folder(self.root/'missing',self.root/'out')
    def test_navigation_wiring_source(self):
        ui=(ROOT/'src/mastering_lab/auto_studio_ui.py').read_text()
        album=(ROOT/'src/mastering_lab/album_studio_ui.py').read_text()
        self.assertIn('backRequested.connect(self._return_from_album)',ui)
        self.assertIn('self.backRequested.emit()',album)
        self.assertIn("self.back_btn.setEnabled(not self._busy())",album)

if __name__ == '__main__': unittest.main()
