"""v0.24.1 smoke regressions: compact Compare UX without losing tested workflow."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


class CompactAutoStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compare = (ROOT / 'unified_comparison.py').read_text(encoding='utf-8')
        cls.studio = (ROOT / 'auto_studio_ui.py').read_text(encoding='utf-8')
        ast.parse(cls.compare)
        ast.parse(cls.studio)

    def test_diagnostics_hidden_without_deleting_metrics(self):
        for key in ('self.diagnostics_panel.hide()',
                    'self.diagnostics_layout.addWidget(self.measure_status)',
                    'self.diagnostics_layout.addWidget(self.gentle_explanation)',
                    'self.diagnostics_layout.addWidget(self.activity_inspector)',
                    'self.diagnostics_layout.addWidget(self.file_status)',
                    'def _toggle_diagnostics(self):'):
            self.assertIn(key, self.compare)

    def test_common_transport_and_markers_kept(self):
        for key in ('self.waveform.markerClicked.connect(self._jump_to_marker)',
                    'self.waveform.setMarkers(', 'self._seek()',
                    'self._update_advisor()', 'def master_source(self, selected_mix):',
                    'self._approved', 'save_choice('):
            self.assertIn(key, self.compare)

    def test_advanced_tools_hidden_but_accessible(self):
        for key in ('self.optional_tools_panel.hide()',
                    'def _toggle_optional_tools(self):',
                    'optional_layout.addWidget(self.ai_status)',
                    'optional_layout.addWidget(self.fx_status)',
                    'optional_layout.addWidget(self._fx_ab_player)',
                    'optional_layout.addLayout(fx_row)',
                    'optional_layout.addLayout(pref_row)'):
            self.assertIn(key, self.studio)

    def test_auto_produce_remains_one_action_not_fake_mastering(self):
        for key in ("self.produce_btn.clicked.connect(self._produce)",
                    'self.stems.start_guided_production()',
                    'self.unified.prepare_automatically()',
                    'self.unified.prepared.connect(self._on_unified_prepared)',
                    'self.continue_btn.clicked.connect(self._continue_mastering)'):
            self.assertIn(key, self.studio)
        self.assertNotIn('self.approve(', self.compare[
            self.compare.index('def _update_advisor(self):'):
            self.compare.index('def preview_suggestion(self):')])
        self.assertIn("APP_VERSION = '0.24.1'",
                      (ROOT / 'version.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
