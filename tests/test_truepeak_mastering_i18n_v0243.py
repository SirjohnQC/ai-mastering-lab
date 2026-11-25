"""v0.24.3: true peak guard and report translation regression tests."""
from pathlib import Path
import ast
import unittest

from mastering_lab.master_report_i18n import format_master_result
from mastering_lab.release_preflight import format_preflight

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def master_result(peak):
    return {'status':'qc_pass' if peak<=-1 else 'needs_review',
            'output_lufs':-14.02, 'target_lufs':-14.0,
            'output_true_peak_dbtp':peak,'target_true_peak_dbtp':-1.0,
            'output':{'sample_rate':48000},'file':'demo.wav',
            'qc_issues':[] if peak<=-1 else ['True peak above ceiling']}


class MasteringI18nTests(unittest.TestCase):
    def test_code_parses(self):
        for filename in ('auto_master.py','auto_studio_ui.py','release_preflight.py',
                         'master_report_i18n.py'):
            ast.parse((ROOT/filename).read_text(encoding='utf-8'))

    def test_true_peak_guard_is_stricter_than_previously(self):
        code=(ROOT/'auto_master.py').read_text(encoding='utf-8')
        self.assertIn('render_tp = target_tp - 0.20',code)
        self.assertIn('TP={render_tp}',code)
        self.assertIn('measured_tp > target_tp:',code)
        self.assertNotIn('measured_tp > target_tp + 0.2',code)
        self.assertIn("'status': 'qc_pass' if not issues else 'needs_review'",code)

    def test_english_french_master_reports(self):
        status_en,report_en=format_master_result(master_result(-1.17),'en')
        status_fr,report_fr=format_master_result(master_result(-1.17),'fr')
        self.assertIn('QC checks passed',status_en)
        self.assertIn('Contrôles QC réussis',status_fr)
        self.assertIn('Integrated loudness',report_en)
        self.assertIn('LUFS intégrés',report_fr)
        self.assertIn('True peak: -1.17',report_en)
        self.assertIn('\n',report_en)
        bad,_=format_master_result(master_result(-.97),'en')
        self.assertIn('review',bad.lower())

    def test_preflight_translates_truepeak_warning(self):
        report={'status':'technical_pass_with_notes',
                'file':{'subtype':'PCM_24','sample_rate':48000,'channels':2,
                        'duration_seconds':70.2},
                'audio':{'sample_peak_dbfs':-.97,'clipped_frames':0,
                         'initial_silence_seconds':0,'final_silence_seconds':.01},
                'loudness':{'integrated_lufs':-14.02,'true_peak_dbtp':-.97},
                'issues':[],'warnings':['True peak supérieur à −1 dBTP : vérifier l’encodage avec pertes.']}
        english=format_preflight(report,'en')
        french=format_preflight(report,'fr')
        self.assertIn('True peak exceeds -1 dBTP',english)
        self.assertIn('True peak supérieur à −1 dBTP',french)
        self.assertIn('\n',english)
        self.assertNotIn('À VÉRIFIER',english)
        self.assertIn('À VÉRIFIER',french)

if __name__=='__main__':
    unittest.main()
