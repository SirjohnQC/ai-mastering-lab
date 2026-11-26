"""v0.26.0 tonal matching: bounded proposals, independent QC, unchanged master."""
from __future__ import annotations
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mastering_lab.album_tonal_preview import tonal_proposal, render_tonal_preview

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


def analyzed(bands):
    return {'status':'measured', 'relative_band_delta_db':bands}


class TonalMatchingTests(unittest.TestCase):
    def test_meaningful_midrange_difference_proposes_gentle_cut(self):
        result=tonal_proposal(analyzed([0,0,7.0,0,0]))
        self.assertEqual(result['kind'],'tonal_eq_preview')
        self.assertEqual(len(result['filters']),1)
        self.assertEqual(result['filters'][0]['frequency_hz'],1200)
        self.assertLess(result['filters'][0]['gain_db'],0)
        self.assertGreaterEqual(result['filters'][0]['gain_db'],-1.25)

    def test_high_frequency_review_is_extra_conservative(self):
        result=tonal_proposal(analyzed([0,0,0,0,-5.2]))
        self.assertEqual(result['filters'][0]['frequency_hz'],11000)
        self.assertLessEqual(result['filters'][0]['gain_db'],.6)

    def test_close_spectra_or_unreliable_spectra_yields_no_B(self):
        for bands in ([0,0,0,0,0],[1.5,2.5,-2.0,3.9,0],
                      [0,0,0,0,-4.9],[0,0,0,0,80]):
            with self.assertRaises(ValueError):
                tonal_proposal(analyzed(bands))

    def test_ineligible_or_corrupt_reports_are_rejected(self):
        for report in (analyzed([0,0,0]),
                       {'status':'not_ready','relative_band_delta_db':[0,0,6,0,0]},
                       analyzed([0,float('nan'),8,0,0]),
                       analyzed([0,0,'bad',0,0])):
            with self.assertRaises(ValueError):
                tonal_proposal(report)

    def test_render_preserves_original_and_measures_a_and_b(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original=root/'master.wav'
            original.write_bytes(b'original WAV bytes unchanged')
            render_calls=[]
            def fake_render(ffmpeg,source,output,filters):
                render_calls.append(filters)
                output.write_bytes(b'non destructive mock WAV with at least 44 bytes.........')
            readings=iter([
                {'input_i':'-14.0','input_tp':'-1.3'}, # A
                {'input_i':'-13.8','input_tp':'-1.3'}, # EQ B uncorrected
                {'input_i':'-14.02','input_tp':'-1.2'},# EQ B level matched
            ])
            with patch('mastering_lab.album_tonal_preview._render',side_effect=fake_render), \
                 patch('mastering_lab.album_tonal_preview._probe_wav',return_value={
                     'channels':2,'frames':48000,'sample_rate':48000,'subtype':'PCM_24'}):
                result=render_tonal_preview(original,analyzed([0,0,7,0,0]),
                    root/'cache',ffmpeg_path='ffmpeg',measure_fn=lambda _:next(readings))
            self.assertEqual(len(render_calls),2)
            self.assertIn('equalizer=',render_calls[0])
            self.assertIn('volume=-0.2000dB',render_calls[1])
            self.assertTrue(Path(result['file']).is_file())
            self.assertEqual(result['status'],'preview_only')
            self.assertFalse(result['approved'])
            self.assertEqual(result['kind'],'tonal_eq_preview')
            self.assertEqual(original.read_bytes(),b'original WAV bytes unchanged')
            self.assertAlmostEqual(result['measured_lufs'],-14.02)
            self.assertLessEqual(result['verified_true_peak_dbtp'],-1)

    def test_true_peak_failure_produces_no_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original=root/'original.wav'
            original.write_bytes(b'original')
            readings=iter([
                {'input_i':-14.0,'input_tp':-1.2},
                {'input_i':-13.9,'input_tp':-1.15},
                {'input_i':-14.0,'input_tp':-0.91}])
            def fake_render(_,__,dest,___):
                dest.write_bytes(b'preview temporary')
            with patch('mastering_lab.album_tonal_preview._render',side_effect=fake_render), \
                 patch('mastering_lab.album_tonal_preview._probe_wav',return_value={
                     'channels':2,'frames':48000,'sample_rate':48000,'subtype':'PCM_24'}):
                with self.assertRaisesRegex(RuntimeError,'true-peak|dBTP|exceeds'):
                    render_tonal_preview(original,analyzed([0,0,7,0,0]),root/'cache',
                        ffmpeg_path='ffmpeg',measure_fn=lambda _:next(readings))
            self.assertFalse(list((root/'cache').glob('album-tonal-ab-*.wav')))
            self.assertEqual(original.read_bytes(),b'original')

    def test_existing_old_preview_and_ui_code_still_parse(self):
        for name in ('album_tonal_preview.py','album_ab_preview.py',
                     'album_studio_ui.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('from .album_tonal_preview import render_tonal_preview',ui)
        self.assertIn('self.player.setPosition(pos)',ui)
        self.assertIn('self.approve_button.clicked.connect(self._approve)',ui)
        self.assertIn("dlg.setWindowTitle('Album A/B · '+row['title'])",ui)
        self.assertIn('self._open_ab_for_song(source)',ui)


if __name__ == '__main__':
    unittest.main()
