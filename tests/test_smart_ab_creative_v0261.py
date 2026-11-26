"""v0.26.1: meaningful decisions and clearly separate creative A/B variants."""
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mastering_lab.album_tonal_preview import (
    CREATIVE_STYLES, PreviewNotNeeded, PreviewUncertain,
    preview_decision, creative_proposal, tonal_proposal, render_tonal_preview,
)

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def row(bands, status='measured'):
    return {'status':status, 'relative_band_delta_db':bands}


class SmartABCreativeTests(unittest.TestCase):
    def test_close_comparison_is_successful_no_change_not_error(self):
        decision=preview_decision(row([0,0,0,0,2.4]))
        self.assertEqual(decision['status'],'already_close')
        self.assertIsNone(decision['proposal'])
        with self.assertRaises(PreviewNotNeeded):
            tonal_proposal(row([0,0,0,0,2.4]))

    def test_untrustworthy_reference_is_distinct_from_close(self):
        self.assertEqual(preview_decision(row([0,0,0,0,90]))['status'],'uncertain')
        self.assertEqual(preview_decision(row([0,0,0],status='not_ready'))['status'],'uncertain')
        self.assertEqual(preview_decision(row([0,0,7,0,0]))['status'],'available')
        with self.assertRaises(PreviewUncertain):
            tonal_proposal(row([0,0,0,0,90]))

    def test_three_creative_styles_are_named_and_limited(self):
        self.assertEqual(set(CREATIVE_STYLES), {'warm','presence','air'})
        for name in CREATIVE_STYLES:
            result=creative_proposal(row([0]*5),style=name)
            self.assertEqual(result['kind'],'creative_eq_preview')
            self.assertEqual(result['style'],name)
            self.assertLessEqual(len(result['filters']),2)
            self.assertTrue(all(abs(f['gain_db'])<=1.25 for f in result['filters']))
            self.assertTrue(all(abs(f['gain_db'])<=.6 for f in result['filters']
                                if f['frequency_hz']==11000))

    def test_creative_does_not_claim_to_match_reference(self):
        for style in ('warm','presence','air'):
            proposed=creative_proposal(row([0,0,0,0,0]),style=style)
            self.assertIn('not a claim',proposed['disclaimer'])
        with self.assertRaises(ValueError):
            creative_proposal(row([0]*5),style='unknown')
        with self.assertRaises(PreviewUncertain):
            creative_proposal(row([0]*5,status='not_ready'))

    def test_creative_renders_with_level_matching_and_no_original_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original=root/'master.wav'
            original.write_bytes(b'original remains the same')
            calls=[]
            def fake_render(_ffmpeg,_src,path,filters):
                calls.append(filters)
                path.write_bytes(b'x'*56)
            measures=iter([
                {'input_i':-14.0,'input_tp':-1.3},
                {'input_i':-13.9,'input_tp':-1.2},
                {'input_i':-14.01,'input_tp':-1.17},
            ])
            with patch('mastering_lab.album_tonal_preview._render',side_effect=fake_render), \
                 patch('mastering_lab.album_tonal_preview._probe_wav',return_value={
                     'channels':2,'frames':48000,'sample_rate':48000,'subtype':'PCM_24'}):
                result=render_tonal_preview(original,row([0]*5),root/'cache',
                    mode='creative',creative_style='warm',ffmpeg_path='ffmpeg',
                    measure_fn=lambda _:next(measures))
            self.assertEqual(len(calls),2)
            self.assertIn('equalizer=',calls[0])
            self.assertIn('volume=-0.1000dB',calls[1])
            self.assertEqual(result['kind'],'creative_eq_preview')
            self.assertEqual(result['creative_style'],'warm')
            self.assertEqual(result['mode'],'creative')
            self.assertFalse(result['approved'])
            self.assertEqual(original.read_bytes(),b'original remains the same')
            self.assertLessEqual(result['verified_true_peak_dbtp'],-1.0)

    def test_ui_mode_picker_and_version_parse(self):
        for name in ('album_tonal_preview.py','album_studio_ui.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for token in ('self.mode_picker=QComboBox()',
                      "('match','')", "('creative','warm')",
                      "('creative','presence')", "('creative','air')",
                      'self.match_decision=preview_decision(self.analysis)',
                      'self.mode_picker.currentIndexChanged.connect(self._mode_changed)',
                      'creative_style=self.creative_style',
                      "self.render_button.setEnabled(state=='available')",
                      'self.player.setPosition(pos)',
                      'self.approve_button.clicked.connect(self._approve)'):
            self.assertIn(token,code)


if __name__=='__main__':
    unittest.main()
