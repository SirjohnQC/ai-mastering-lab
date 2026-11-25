"""Regression for clickable listening markers on the actual shared waveform."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT/'src'/'mastering_lab'


class WaveformMarkerDisplayTests(unittest.TestCase):
    def test_waveform_has_marker_signal_and_paint_path(self):
        s=(PKG/'waveform_preview.py').read_text(encoding='utf-8')
        ast.parse(s)
        for expected in ('markerClicked = Signal(int)', 'def setMarkers(self, markers):',
                         "QColor('#fa81bb')", 'self.markerClicked.emit(index)'):
            self.assertIn(expected,s)

    def test_unified_player_connects_same_audition_jump(self):
        s=(PKG/'unified_comparison.py').read_text(encoding='utf-8')
        m=ast.parse(s)
        funcs={n.name:ast.get_source_segment(s,n) for n in ast.walk(m)
               if isinstance(n, ast.FunctionDef)}
        self.assertIn('self.waveform.markerClicked.connect(self._jump_to_marker)',s)
        self.assertIn('self.waveform.setMarkers(',funcs['_set_review_markers'])
        self.assertIn('self._seek()',funcs['_jump_to_marker'])
        self.assertNotIn('self.approve(',funcs['_jump_to_marker'])
        self.assertIn("if marker_variant == 'original':",funcs['_update_active_diagnostics'])
        self.assertIn('self._set_review_markers(window_for_markers',funcs['_update_active_diagnostics'])

if __name__=='__main__':
    unittest.main()
