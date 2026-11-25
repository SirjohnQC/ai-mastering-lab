"""Structural regression checks, runnable without PySide6."""
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'src/mastering_lab/auto_studio_ui.py'

class ImportLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding='utf-8')
        cls.block = cls.source.split('        # IMPORT', 1)[1].split('        # PRODUCING', 1)[0]

    def test_list_precedes_import_controls(self):
        self.assertLess(self.block.index('v.addWidget(self.stem_list_scroll, 3)'), self.block.index("title = QLabel('Ta musique"))
        self.assertLess(self.block.index('v.addWidget(self.stem_list_scroll, 3)'), self.block.index("self.produce_btn = QPushButton"))

    def test_list_not_height_capped(self):
        self.assertNotIn('stem_list_scroll.setMaximumHeight', self.block)
        self.assertIn('QSizePolicy.Expanding, QSizePolicy.Expanding', self.block)

    def test_empty_and_populated_stretches(self):
        self.assertIn('self.import_layout.setStretch(self._import_top_spacer, 0 if has_files else 1)', self.source)
        self.assertIn('self.import_layout.setStretch(self._import_bottom_spacer, 0 if has_files else 2)', self.source)

    def test_safe_removal_intact(self):
        self.assertIn('self.stems.remove_stem_from_selection(file_path)', self.source)
        self.assertIn("remove.clicked.connect(lambda checked=False, f=file_path: self._remove_stem(f))", self.source)

    def test_render_and_master_unchanged(self):
        self.assertIn('def _open_master_stage(self)', self.source)
        self.assertIn('def _produce(self)', self.source)

if __name__ == '__main__':
    unittest.main()
