import sys, tempfile, unittest, json
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.pro_c3_testbench import bench_and_save, RATE, summarize

class RenderShapeTests(unittest.TestCase):
    def run_bench(self, root, extra=0, rate=RATE, channels=2, tail=64):
        root=Path(root); host=root/'host.exe';host.touch();plugin=root/'Pro-C 3.vst3';plugin.mkdir()
        names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
        def runner(host, mode, **kw):
            if mode=='inspect':
                return {'name':'Pro-C 3','parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
            a,sr=sf.read(str(kw['input_file']), dtype='float32', always_2d=True)
            a[RATE:2*RATE]*=.4;a[3*RATE:]*=.4
            if extra>0: a=np.concatenate([a,np.zeros((extra,2),dtype='float32')])
            if extra<0: a=a[:extra]
            if channels==1:a=a[:,0]
            sf.write(str(kw['output_file']), a,rate)
            return {'parameter_changes':[{'index':19,'text':'Off'}], 'tail_samples':tail}
        return bench_and_save(root, host=host, plugin=plugin, runner=runner)
    def test_exact_64_tail_analyzed_but_not_approved(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.run_bench(d,extra=64)
            self.assertEqual(r['status'],'needs_review')
            self.assertEqual(r['wav_shape']['observed']['frames'],RATE*4+64)
            self.assertEqual(r['wav_shape']['trailing_tail_for_measurement'],64)
            self.assertFalse(r['automatic_compression_enabled'])
            self.assertIn('WAV rendu', summarize(r))
    def test_same_length_declared_tail_is_review(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.run_bench(d)
            self.assertEqual(r['status'],'needs_review')
            self.assertEqual(r['wav_shape']['trailing_tail_for_measurement'],0)
    def test_unexplained_tail_rejected_with_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'longueur non expliquée'):
                self.run_bench(d,extra=128)
            report=next((Path(d)/'settings/pro_c3_testbench').glob('*/report.json'))
            self.assertEqual(json.loads(report.read_text())['wav_shape']['observed']['frames'],RATE*4+128)
    def test_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'tronqué'):
                self.run_bench(d,extra=-64)
    def test_changed_rate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'canaux ou fréquence'):
                self.run_bench(d,rate=44100)
    def test_changed_channels_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'canaux ou fréquence'):
                self.run_bench(d,channels=1)

if __name__=='__main__':unittest.main()
