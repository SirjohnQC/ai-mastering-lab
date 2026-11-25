import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mastering_lab.pro_c3_audition import audition_sources, store_preference

class FakeInfo:
    def __init__(self,frames):
        self.frames = frames
        self.channels = 2
        self.samplerate = 48000


class TestSyntheticAudition(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root/'settings/pro_c3_parameter_validation/20261124-230146-test'
        self.folder.mkdir(parents=True)
        for kind in ['before','gentle-pro-c3','firm-pro-c3']:
            (self.folder / ('synthetic-'+kind+'.wav')).touch()
        self.report = {'kind':'pro_c3_parameter_validation','status':'needs_review',
                       'ready_to_render':False,'automatic_compression_enabled':False,
                       'created_utc':'2026-11-24T23:01:46Z',
                       'comparison':{'firm_more_compression_observed':True},
                       'scenarios':{}}
        for kind in ['gentle','firm']:
            self.report['scenarios'][kind] = {'output_path':str(self.folder/f'synthetic-{kind}-pro-c3.wav'),
               'parameters':{'threshold':{'actual_physical':-18.0}},
               'measurements':{'nonzero_output':True}, 'declared_tail_samples':64}
        self.write_report()

    def write_report(self):
        (self.folder/'report.json').write_text(json.dumps(self.report))

    @patch('soundfile.info')
    def test_valid_wavs(self, info):
        info.side_effect=lambda path:FakeInfo(192000 if path.endswith('before.wav') else 192064)
        paths, report=audition_sources(self.root)
        self.assertEqual(set(paths),{'original','gentle','firm'})
        self.assertEqual(report['kind'],'pro_c3_parameter_validation')

    @patch('soundfile.info')
    def test_bad_tail_rejected(self,info):
        info.side_effect=lambda path:FakeInfo(192000 if path.endswith('before.wav') else 192999)
        with self.assertRaisesRegex(ValueError,'Dimensions'):
            audition_sources(self.root)

    @patch('soundfile.info')
    def test_external_song_path_rejected(self,info):
        self.report['scenarios']['firm']['output_path']=str(self.root/'my-song.wav')
        self.write_report()
        with self.assertRaisesRegex(ValueError,'Chemin'):
            audition_sources(self.root)

    def test_failed_report_rejected(self):
        self.report['status']='failed';self.write_report()
        with self.assertRaisesRegex(ValueError,'exploitable'):
            audition_sources(self.root)

    def test_save_preference_only_after_choice(self):
        result=store_preference(self.root,self.report,'gentle')
        record=json.loads(result.read_text().strip())
        self.assertEqual(record['selected'],'gentle')
        self.assertFalse(record['use_for_hermes'])
        self.assertFalse(record['automatic_compression_enabled'])

    def test_invalid_choice_rejected(self):
        with self.assertRaises(ValueError):
            store_preference(self.root,self.report,'unknown')
        self.assertFalse((self.root/'settings/pro_c3_audition_preferences.jsonl').exists())

if __name__=='__main__':unittest.main()
