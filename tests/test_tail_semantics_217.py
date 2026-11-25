import sys, tempfile, unittest, json
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from mastering_lab.pro_c3_testbench import bench_and_save, RATE, summarize

class TailTests(unittest.TestCase):
    def mock_run(self, root, tail, bad_length=False):
        root=Path(root); h=root/'mastering-host.exe';h.touch();p=root/'FabFilter Pro-C 3.vst3';p.mkdir()
        names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
        def runner(host, mode, **kw):
            if mode=='inspect':
                return {'name':'FabFilter Pro-C 3','parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
            a,r=sf.read(kw['input_file'], dtype='float32', always_2d=True)
            a[RATE:2*RATE]*=.45;a[3*RATE:]*=.45
            if bad_length:a=a[:-100]
            sf.write(kw['output_file'],a,r)
            return {'parameter_changes':[{'index':19,'text':'Off'}], 'tail_samples':tail}
        return bench_and_save(root,host=h,plugin=p,runner=runner)

    def test_nonzero_tail_is_review_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.mock_run(d,48000)
            self.assertEqual(r['status'],'needs_review')
            self.assertTrue(r['measurements']['compression_observed'])
            self.assertEqual(r['declared_tail_samples'],48000)
            self.assertIn('Queue',summarize(r))
            self.assertFalse(r['automatic_compression_enabled'])
            stored=json.loads(Path(r['report_path']).read_text(encoding='utf-8'))
            self.assertEqual(stored['status'],'needs_review')

    def test_actual_changed_frame_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'durée'):
                self.mock_run(d,48000,bad_length=True)
            files=list((Path(d)/'settings/pro_c3_testbench').glob('*/report.json'))
            self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text())['status'],'failed')

    def test_zero_tail_proceeds_as_before(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.mock_run(d,0)
            self.assertEqual(r['status'],'observed')
            self.assertEqual(r['declared_tail_samples'],0)

if __name__=='__main__':unittest.main()
