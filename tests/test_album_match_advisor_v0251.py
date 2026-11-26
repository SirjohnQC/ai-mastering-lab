"""v0.25.1 Album Match Advisor: bounded non-destructive suggestions."""
import ast
from pathlib import Path
import unittest

from mastering_lab.album_match_advisor import advise_album, localized_card

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


def report(rows):
    return {'schema_version':1,'reference_index':0,
            'reference_title':'Reference','tracks':rows}


def row(index, status='measured', lufs=0, tp=-1.2, bands=None):
    return {'index':index, 'title':f'Song {index}',
            'status':status,'lufs_delta':lufs,'true_peak_dbtp':tp,
            'relative_band_delta_db':bands if bands is not None else [0]*5}


class AlbumMatchAdvisorTests(unittest.TestCase):
    def test_moderate_difference_does_not_force_processing(self):
        advice=advise_album(report([row(0,'reference'),row(1,lufs=-.4,bands=[0,0,1,0,0])]))
        self.assertEqual(advice['tracks'][1]['priority'],'close')
        self.assertEqual(advice['tracks'][1]['recommendations'][0]['kind'],'close')

    def test_loudness_is_listening_direction_not_exact_gain(self):
        advice=advise_album(report([row(0,'reference'),row(1,lufs=-2.0)]))
        notes=advice['tracks'][1]['recommendations']
        self.assertEqual(notes[0]['kind'],'loudness')
        self.assertEqual(notes[0]['direction'],'quieter')
        self.assertNotIn('gain_db',notes[0])
        self.assertIn('niveau perçu',localized_card(advice['tracks'][1],'fr'))
        self.assertIn('perceived level',localized_card(advice['tracks'][1],'en'))

    def test_spectral_region_is_cautious_and_not_eq_value(self):
        advice=advise_album(report([row(0,'reference'),row(1,bands=[0,0,0,6.2,0])]))
        note=advice['tracks'][1]['recommendations'][0]
        self.assertEqual(note['kind'],'spectrum')
        self.assertEqual(note['band_index'],3)
        self.assertEqual(note['direction'],'higher')
        self.assertNotIn('eq_gain_db',note)

    def test_extreme_sparse_spectrum_not_translated_into_eq(self):
        advice=advise_album(report([row(0,'reference'),row(1,bands=[-75,0,0,0,0])]))
        notes=advice['tracks'][1]['recommendations']
        self.assertEqual(notes[0]['kind'],'spectrum_unreliable')
        self.assertFalse(any(n['kind']=='spectrum' for n in notes))

    def test_qc_missing_or_invalid_is_never_recommended(self):
        data=report([row(0,'reference'),{'index':1,'title':'Broken','status':'not_ready'},
                     row(2,lufs=float('nan'))])
        advice=advise_album(data)
        self.assertEqual(advice['tracks'][1]['priority'],'not_ready')
        self.assertEqual(advice['tracks'][2]['priority'],'not_ready')
        self.assertIn('QC master',localized_card(advice['tracks'][1],'en'))

    def test_technical_true_peak_over_ceiling_is_flagged(self):
        advice=advise_album(report([row(0,'reference'),row(1,tp=-.97)]))
        self.assertIn('true_peak',[n['kind'] for n in advice['tracks'][1]['recommendations']])

    def test_ui_wiring_remains_read_only(self):
        for name in ('album_match_advisor.py','album_studio_ui.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('advice = advise_album(report)',ui)
        self.assertIn('localized_card(',ui)
        self.assertIn("'album_match_advice.json'",ui)
        model=(ROOT/'album_match_advisor.py').read_text(encoding='utf-8')
        for forbidden in ('master_song(', 'sf.write(', 'ffmpeg', 'apply_eq(', 'urlopen('):
            self.assertNotIn(forbidden,model)


if __name__ == '__main__':
    unittest.main()
