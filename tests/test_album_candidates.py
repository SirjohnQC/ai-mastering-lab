import sys, types, tempfile, unittest, pathlib
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

# Dependencies supplied by the user's existing project. Stub them for isolated
# contract tests, keeping the patch independent of installed audio hardware.
stem = types.ModuleType('mastering_lab.stem_mixer')
stem.config_template = lambda folder: {'tracks':[{'file':'Lead Vocals.wav','gain_db':0}, {'file':'Drums.wav','gain_db':0}]}
stem.render_mix = None
sys.modules['mastering_lab.stem_mixer'] = stem
mix = types.ModuleType('mastering_lab.auto_mix_candidates')
mix.VARIANTS = ('balanced','vocal-focus','punchy')
def candidates(config):
    return {x: {'tracks': [dict(t, eq=False) for t in config['tracks']], 'variant':x} for x in mix.VARIANTS}
mix.candidate_configs = candidates
sys.modules['mastering_lab.auto_mix_candidates'] = mix
master = types.ModuleType('mastering_lab.auto_master')
class MasteringCancelled(Exception): pass
master.MasteringCancelled = MasteringCancelled
master.master_song = None
sys.modules['mastering_lab.auto_master'] = master
from mastering_lab.album_stem_pipeline import master_stem_folder, can_reuse_master, PIPELINE_ID

class AlbumVariantsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.stems = self.root/'stems'; self.stems.mkdir()
        for name in ('Lead Vocals.wav','Drums.wav'):
            (self.stems/name).write_bytes(b'dummy audio')
    def test_three_candidates_master_balanced(self):
        calls=[]
        def render(folder, config, out):
            calls.append(config['variant']); out.write_bytes(b'wav'); return {'status':'ok'}
        def master_fn(source, output, *, stop=None):
            self.assertEqual(source.name,'balanced.wav')
            output.mkdir(exist_ok=True,parents=True)
            target=output/'master.wav'; target.write_bytes(b'master')
            return {'status':'qc_pass','file':str(target)}
        result=master_stem_folder(self.stems,self.root/'exports',render_mix_fn=render,master_fn=master_fn)
        self.assertEqual(calls,['balanced','vocal-focus','punchy'])
        self.assertEqual(result['album_pipeline'],PIPELINE_ID)
        self.assertEqual(len(result['album_candidates']),3)
        self.assertTrue(pathlib.Path(result['album_candidates_manifest']).is_file())
        row={'status':'qc_pass','kind':'stems','path':str(self.stems),'result':result}
        self.assertTrue(can_reuse_master(row))
        (self.stems/'Drums.wav').write_bytes(b'changed')
        self.assertFalse(can_reuse_master(row))
    def test_old_stems_result_never_reused(self):
        from mastering_lab.album_stem_pipeline import source_signature
        target=self.root/'old.wav'; target.write_bytes(b'x')
        row={'status':'qc_pass','kind':'stems','path':str(self.stems),'result':{'file':str(target),'status':'qc_pass','album_source_signature':source_signature(self.stems,'stems'),'album_pipeline':'dry_stems_to_stereo_then_technical_master'}}
        self.assertFalse(can_reuse_master(row))
    def test_cancelled_before_render(self):
        import threading
        cancel=threading.Event();cancel.set()
        with self.assertRaises(MasteringCancelled):
            master_stem_folder(self.stems,self.root/'output',stop=cancel)

if __name__=='__main__': unittest.main()
