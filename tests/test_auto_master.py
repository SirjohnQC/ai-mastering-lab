from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from src.mastering_lab.auto_master import _json_report, MasteringError, master_song


class AutoMasterTests(unittest.TestCase):
    def test_ffmpeg_report_parsing(self):
        msg = '''[Parsed_loudnorm_0] \n{ "input_i" : "-17.8", "input_tp" : "-3.8", "input_lra" : "4.0", "input_thresh" : "-28.7", "target_offset" : "0.0" }'''
        self.assertEqual(float(_json_report(msg)['input_i']), -17.8)

    def test_invalid_report_rejected(self):
        with self.assertRaises(MasteringError):
            _json_report('nothing useful here')

    def test_missing_source(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(MasteringError):
                master_song(Path(td) / 'missing.wav', Path(td))

    def test_out_of_range_rejected(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'in.wav'; sf.write(p, np.zeros((1000, 2)), 48000)
            with self.assertRaises(MasteringError):
                master_song(p, Path(td), target_lufs=-3)

    def test_real_wav_master_and_qc(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'in.wav'
            sr = 48000
            t = np.arange(sr * 5, dtype=np.float64)/sr
            sample = .075*np.sin(2*np.pi*220*t) + .025*np.sin(2*np.pi*440*t)
            sf.write(p, np.column_stack([sample, np.roll(sample, 11)]), sr, subtype='PCM_24')
            original_bytes = p.read_bytes()
            output = master_song(p, Path(td) / 'out')
            self.assertEqual(output['status'], 'qc_pass')
            self.assertEqual(output['output']['subtype'], 'PCM_24')
            self.assertEqual(output['output']['sample_rate'], sr)
            self.assertEqual(output['output']['channels'], 2)
            self.assertLessEqual(output['output_true_peak_dbtp'], -0.8)
            self.assertLess(abs(output['output_lufs'] + 14), 1)
            self.assertTrue(Path(output['file']).is_file())
            self.assertTrue(Path(output['file']).with_suffix('.qc.json').is_file())
            self.assertEqual(original_bytes, p.read_bytes())

    def test_mono_rejected(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'mono.wav'
            sf.write(source, np.zeros(48000), 48000)
            with self.assertRaisesRegex(MasteringError, 'stéréo'):
                master_song(source, Path(td) / 'out')

    def test_immediate_cancel_preserves_input(self):
        import numpy as np
        import soundfile as sf
        import threading
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'song.wav'
            x = np.sin(np.arange(48000)/48000 * 220 * 6.283) * 0.1
            sf.write(source, np.column_stack([x, x]), 48000)
            original = source.read_bytes()
            stop = threading.Event(); stop.set()
            from src.mastering_lab.auto_master import MasteringCancelled
            with self.assertRaises(MasteringCancelled):
                master_song(source, Path(td) / 'out', stop=stop)
            self.assertEqual(source.read_bytes(), original)

    def test_ui_has_master_stage(self):
        content = (Path(__file__).parent.parent / 'src/mastering_lab/auto_studio_ui.py').read_text()
        for text in ['AutoMasterWorker', 'master_song', 'self.stack.addWidget(master)',
                     'def _cancel_master', "self._go(3)", 'def _continue_mastering']:
            self.assertIn(text, content)


if __name__ == '__main__': unittest.main()
