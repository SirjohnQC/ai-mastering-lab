import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.album_project import (empty_project, save_project, load_project,
                                        add_entries, discover_album, album_summary)

class AlbumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wav1 = self.root/'01-One.wav'; self.wav1.write_bytes(b'RIFFtest')
        self.wav2 = self.root/'02-Two.wav'; self.wav2.write_bytes(b'RIFFtest')
        self.stems = self.root/'SongThree'/'stems'; self.stems.mkdir(parents=True)
        (self.stems/'vocals.wav').write_bytes(b'x')
        (self.stems/'drums.wav').write_bytes(b'x')
    def tearDown(self): self.temp.cleanup()
    def test_add_and_dedupe(self):
        p=empty_project()
        self.assertEqual(add_entries(p,[self.wav1,self.wav1],'stereo'),1)
        self.assertEqual(len(p['tracks']),1)
    def test_stem_group(self):
        p=empty_project();add_entries(p,[self.stems],'stems')
        self.assertEqual(p['tracks'][0]['kind'],'stems')
    def test_discover(self):
        rows=discover_album(self.root)
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(kind=='stems' for _,kind in rows),1)
    def test_persistence_and_order(self):
        p=empty_project();add_entries(p,[self.wav1,self.wav2],'stereo')
        p['tracks'].reverse()
        dest=self.root/'settings'/'album_project.json'
        save_project(dest,p)
        self.assertEqual(load_project(dest)['tracks'][0]['title'],'02-Two')
    def test_summary_no_fake_qc(self):
        p=empty_project();add_entries(p,[self.wav1,self.stems], 'stereo') if False else None
        add_entries(p,[self.wav1],'stereo');add_entries(p,[self.stems],'stems')
        self.assertEqual(album_summary(p)['qc_pass_count'],0)
    def test_invalid_entry(self):
        with self.assertRaises(ValueError): add_entries(empty_project(),[self.root/'missing.wav'],'stereo')
    def test_invalid_version(self):
        path=self.root/'bad.json';path.write_text('{"schema":99,"tracks":[]}')
        with self.assertRaises(ValueError):load_project(path)

if __name__=='__main__':unittest.main()
