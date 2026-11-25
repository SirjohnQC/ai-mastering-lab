import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.pro_c3_testbench import build_probe, measure_response, bench_and_save, RATE

class BenchTests(unittest.TestCase):
    def test_probe_synthetic_stereo(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'in.wav';build_probe(p)
            meta=sf.info(p)
            self.assertEqual((meta.frames, meta.samplerate, meta.channels), (RATE*4, RATE, 2))
            a,_=sf.read(p, always_2d=True)
            self.assertGreater(float(np.max(np.abs(a[RATE:2*RATE]))), 0.4)
            self.assertLess(float(np.max(np.abs(a[0:RATE]))), 0.05)

    def test_response_detects_loud_compression(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Path(tmp)/'before.wav';a=Path(tmp)/'after.wav';build_probe(b)
            arr,r=sf.read(b, dtype='float32', always_2d=True)
            arr[RATE:2*RATE]*=0.45
            arr[3*RATE:]*=0.45
            sf.write(a,arr,r)
            m=measure_response(b,a)
            self.assertTrue(m['compression_observed'])
            self.assertGreater(m['high_level_attenuation_db'],6)

    def test_no_change_not_marked_as_compressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'same.wav';build_probe(p)
            self.assertFalse(measure_response(p,p)['compression_observed'])

    def test_run_mocked_host_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);host=root/'mastering-host.exe';host.touch();plugin=root/'FabFilter Pro-C 3.vst3';plugin.mkdir()
            names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
            info={'name':'FabFilter Pro-C 3', 'parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
            def runner(host, mode, **kw):
                if mode=='inspect':return info
                self.assertEqual(kw['parameter_changes'],[(19,0.0)])
                signal,sr=sf.read(kw['input_file'],dtype='float32',always_2d=True)
                signal[RATE:2*RATE]*=.45;signal[3*RATE:]*=.45
                sf.write(kw['output_file'],signal,sr)
                return {'parameter_changes':[{'index':19,'text':'Off'}], 'tail_samples':0}
            result=bench_and_save(root,host=host,plugin=plugin,runner=runner)
            self.assertEqual(result['status'],'observed')
            stored=json.loads(Path(result['report_path']).read_text())
            self.assertFalse(stored['ready_to_render'])
            self.assertFalse(stored['automatic_compression_enabled'])
            self.assertTrue(Path(result['before_path']).exists())

    def test_auto_gain_must_be_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);host=root/'mastering-host.exe';host.touch();plugin=root/'FabFilter Pro-C 3.vst3';plugin.mkdir()
            names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
            def runner(h,mode,**kw):
                if mode=='inspect':return {'name':'Pro-C 3','parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
                sf.write(kw['output_file'],np.zeros((RATE*4,2)),RATE)
                return {'parameter_changes':[{'index':19,'text':'On'}], 'tail_samples':0}
            with self.assertRaisesRegex(ValueError,'Auto Gain'):
                bench_and_save(root,host=host,plugin=plugin,runner=runner)
            files=list((root/'settings/pro_c3_testbench').glob('*/report.json'))
            self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text())['status'],'failed')

if __name__=='__main__': unittest.main()
