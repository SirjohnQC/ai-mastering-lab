"""v0.23.6 regression tests: sample-derived review markers in shared Compare transport."""
from __future__ import annotations
import ast
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from mastering_lab.transient_guard import compare_windows

ROOT = Path(__file__).resolve().parents[1]


def render_pair(folder, *, duration_s=18, effect=True):
    """Synthetic alternating loud/quiet material; a strong affected section."""
    rate = 48000
    n = rate * duration_s
    times = np.arange(n, dtype=np.float64) / rate
    loud = ((times.astype(int) % 4) < 2)
    src = (np.sin(2 * np.pi * 200 * times)
           * np.where(loud, 0.75, 0.13))
    gain = np.where((times >= 8) & (times < 12) & loud, 0.22, 1.0) if effect else 1.0
    dst = src * gain
    original = folder / 'original.wav'
    compressed = folder / 'compressed.wav'
    sf.write(str(original), np.column_stack([src, src]), rate, subtype='FLOAT')
    sf.write(str(compressed), np.column_stack([dst, dst]), rate, subtype='FLOAT')
    return original, compressed


class ReviewMarkerTests(unittest.TestCase):
    def test_affected_windows_generate_bounded_separated_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            a, b = render_pair(Path(temp))
            result = compare_windows(a, b)
        self.assertEqual(result['status'], 'measured')
        markers = result['review_markers']
        self.assertTrue(markers)
        self.assertLessEqual(len(markers), 3)
        self.assertTrue(any(8000 <= m['source_ms'] < 12000 for m in markers))
        self.assertTrue(all(m['seek_ms'] <= m['source_ms'] for m in markers))
        self.assertTrue(all(m['seek_ms'] >= 0 for m in markers))
        self.assertTrue(all(
            abs(x['source_ms'] - y['source_ms']) >= 4000
            for i, x in enumerate(markers) for y in markers[i+1:]))
        self.assertEqual(markers, sorted(markers, key=lambda m:m['source_ms']))

    def test_identical_files_generate_no_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            a, _ = render_pair(Path(temp), effect=False)
            result = compare_windows(a, a)
        self.assertEqual(result['review_markers'], [])

    def test_ui_marker_jump_uses_common_transport_not_master_approval(self):
        code=(ROOT/'src'/'mastering_lab'/'unified_comparison.py').read_text(encoding='utf-8')
        module=ast.parse(code)
        functions={node.name:ast.get_source_segment(code,node) for node in ast.walk(module)
                   if isinstance(node,ast.FunctionDef)}
        jump=functions['_jump_to_marker']
        self.assertIn('self._seek()', jump)
        self.assertIn('self.toggle()', jump)
        self.assertNotIn('self.approve(', jump)
        self.assertNotIn('save_choice(', jump)
        self.assertIn('self._set_review_markers(', functions['_update_active_diagnostics'])
        self.assertIn('self._approved', functions['master_source'])
        self.assertIn("cache.get('diagnostics_version') == 3", code)
        self.assertIn("'diagnostics_version': 3", code)


if __name__ == '__main__':
    unittest.main()
