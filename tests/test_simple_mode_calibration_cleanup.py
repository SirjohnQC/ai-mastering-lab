"""Tests for the v0.21.4 safe UI relocation. No Qt installation required."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'src/mastering_lab/auto_studio_ui.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'src/mastering_lab/version.py').read_text(encoding='utf-8')

class SimpleModeCleanupTests(unittest.TestCase):
    def test_calibration_buttons_are_not_in_compare_layout(self):
        for name in ('fx_pro_c3', 'fx_pro_c3_report', 'fx_pro_c3_probe', 'fx_pro_c3_probe_report'):
            self.assertNotIn(f'rv.addWidget(self.{name})', SRC)
            self.assertIn(f'tools_layout.addWidget(self.{name})', SRC)

    def test_developer_tools_menu_available(self):
        self.assertIn("menu_bar.addMenu('Tools')", SRC)
        self.assertIn("menu.addAction('Plugin Calibration — Pro-C 3…')", SRC)
        self.assertIn('action.triggered.connect(self._show_calibration_tools)', SRC)

    def test_calibration_workers_and_reports_still_wired(self):
        for connect in ('self._diagnose_pro_c3', 'self._probe_pro_c3',
                        'self._show_pro_c3_report', 'self._show_pro_c3_probe_report'):
            self.assertIn(f'.clicked.connect({connect})', SRC)
        self.assertIn('self.fx_pro_c3.setEnabled(True)', SRC)
        self.assertIn('self.fx_pro_c3_probe.setEnabled(True)', SRC)

    def test_dialog_retained_during_async_work(self):
        self.assertIn('self._calibration_dialog = QDialog(self)', SRC)
        self.assertIn('self.fx_status.textChanged.connect(self._calibration_status.setText)', SRC)
        self.assertIn('close_calibration.clicked.connect(self._calibration_dialog.hide)', SRC)

    def test_simple_workflow_unchanged(self):
        for label in ('Importer', 'Produire', 'Comparer', 'Mastering', 'AI FX — essai EQ', 'Continuer vers Mastering'):
            self.assertIn(label, SRC)
        self.assertIn('self._continue_mastering', SRC)
        self.assertIn('self._start_fx_worker', SRC)

    def test_version_bumped(self):
        self.assertIn("APP_VERSION = '0.21.4'", VERSION)
        self.assertIn('def window_title()', VERSION)

if __name__ == '__main__': unittest.main()
