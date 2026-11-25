import sys, tempfile, unittest
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.pro_c3_testbench import build_probe, measure_pilot_alignment, RATE, PILOT_START, PILOT_LENGTH

class PilotAlignmentTests(unittest.TestCase):
    def test_undelayed_with_64_frames_trailing(self):
        with tempfile.TemporaryDirectory() as d:
            before=Path(d)/'before.wav';after=Path(d)/'after.wav';build_probe(before)
            a,r=sf.read(before, dtype='float32',always_2d=True)
            sf.write(after,np.vstack([a,np.zeros((64,2),'float32')]),RATE)
            result=measure_pilot_alignment(before,after)
            self.assertEqual(result['status'],'measured')
            self.assertEqual(result['pilot_lag_frames'],0)
    def test_delayed_by_64(self):
        with tempfile.TemporaryDirectory() as d:
            before=Path(d)/'before.wav';after=Path(d)/'after.wav';build_probe(before)
            a,r=sf.read(before,dtype='float32', always_2d=True)
            sf.write(after,np.vstack([np.zeros((64,2),'float32'),a]),RATE)
            result=measure_pilot_alignment(before,after)
            self.assertEqual(result['status'],'measured')
            self.assertEqual(result['pilot_lag_frames'],64)
    def test_unrelated_audio_inconclusive(self):
        with tempfile.TemporaryDirectory() as d:
            before=Path(d)/'before.wav';after=Path(d)/'after.wav';build_probe(before)
            sf.write(after,np.zeros((RATE*4+64,2),'float32'),RATE)
            self.assertEqual(measure_pilot_alignment(before,after)['status'],'inconclusive')

if __name__=='__main__':unittest.main()
