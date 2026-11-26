"""v0.26.3: retry gentler EQ when Creative B breaches the true-peak ceiling."""
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mastering_lab.album_tonal_preview import render_tonal_preview, ADAPTIVE_EQ_STRENGTHS

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


class PeakFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.master=self.path/'original.wav'
        self.master.write_bytes(b'untouched original master')

    def run_render(self, readings):
        calls=[]
        values=iter(readings)
        def fake_render(_ffmpeg,_source,out,chain):
            calls.append(chain)
            out.write_bytes(b'X'*64)
        with patch('mastering_lab.album_tonal_preview._render',side_effect=fake_render), \
             patch('mastering_lab.album_tonal_preview._probe_wav',return_value={
                 'channels':2,'frames':48000,'sample_rate':48000,'subtype':'PCM_24'}):
            result=render_tonal_preview(
                self.master,{'status':'measured','relative_band_delta_db':[0]*5},
                self.path/'cache',mode='creative',creative_style='presence',
                ffmpeg_path='ffmpeg',measure_fn=lambda _:next(values))
        return result,calls

    def test_safe_preview_after_reduce_strength(self):
        result,calls=self.run_render([
            {'input_i':-14,'input_tp':-1.20},
            {'input_i':-13.90,'input_tp':-1.1},
            {'input_i':-14,'input_tp':-0.87},
            {'input_i':-13.95,'input_tp':-1.15},
            {'input_i':-14.01,'input_tp':-1.09},
        ])
        self.assertEqual(result['eq_strength'],0.75)
        self.assertEqual(result['mode'],'creative')
        self.assertEqual(result['creative_style'],'presence')
        self.assertEqual(len(calls),4)
        self.assertTrue(Path(result['file']).is_file())
        self.assertLessEqual(result['verified_true_peak_dbtp'],-1.0)
        self.assertFalse(result['approved'])
        self.assertEqual(self.master.read_bytes(),b'untouched original master')

    def test_all_unsafe_attempts_refuse_b(self):
        readings=[{'input_i':-14,'input_tp':-1.2}]
        for _ in ADAPTIVE_EQ_STRENGTHS:
            readings.extend([{'input_i':-13.9,'input_tp':-1.2},
                             {'input_i':-14,'input_tp':-0.9}])
        with self.assertRaisesRegex(RuntimeError,'still exceeds'):
            self.run_render(readings)
        self.assertFalse(list((self.path/'cache').glob('album-tonal-ab-*.wav')))
        self.assertEqual(self.master.read_bytes(),b'untouched original master')

    def test_ui_labels_and_ast(self):
        for file in ('album_tonal_preview.py','album_studio_ui.py'):
            ast.parse((ROOT/file).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn("'B · Creative '+style.title()",ui)
        self.assertIn("result.get('eq_strength',1.0)",ui)
        self.assertIn('intensité adaptée',ui)


if __name__=='__main__':
    unittest.main()
