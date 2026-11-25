import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.album_export_naming import safe_slug, song_name, rename_album_master

class TestAlbumExportNaming(unittest.TestCase):
    def test_song_from_stems_folder(self):
        self.assertEqual(song_name(Path('Music/All We Know Is Falling/stem')), 'All We Know Is Falling')
        self.assertEqual(song_name(Path('Music/Kids in Love/stems')), 'Kids in Love')
        self.assertEqual(song_name(Path('Music/My Song')), 'My Song')
    def test_safe_slug(self):
        self.assertEqual(safe_slug('All We Know Is Falling'), 'all-we-know-is-falling')
        self.assertEqual(safe_slug('Été: 2004?'), 'ete-2004')
    def test_rename_preserves_qc_and_file(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            old=folder/'balanced-master-20261123-183130-414144.wav'
            old.write_bytes(b'fake wav data')
            old.with_suffix('.qc.json').write_text(json.dumps({'file':str(old),'status':'qc_pass'}))
            result=rename_album_master({'file':str(old),'status':'qc_pass'},'All We Know Is Falling','balanced')
            new=folder/'all-we-know-is-falling_balanced-master-20261123-183130-414144.wav'
            self.assertEqual(Path(result['file']),new)
            self.assertEqual(new.read_bytes(),b'fake wav data')
            self.assertFalse(old.exists())
            self.assertEqual(json.loads(new.with_suffix('.qc.json').read_text())['file'],str(new))
    def test_qc_review_name(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d)/'punchy-QC-REVIEW-20261123-183130-414144.wav'
            old.write_bytes(b'audio')
            r=rename_album_master({'file':str(old),'status':'needs_review'},'Song','punchy')
            self.assertEqual(Path(r['file']).name,'song_punchy-QC-REVIEW-20261123-183130-414144.wav')
    def test_stereo_name(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d)/'raw-master-20261123-183130-414144.wav'
            old.write_bytes(b'audio')
            r=rename_album_master({'file':str(old)},'Kids in Love')
            self.assertEqual(Path(r['file']).name,'kids-in-love-master-20261123-183130-414144.wav')
    def test_existing_target_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d)/'balanced-master-20261123-183130-414144.wav'
            old.write_bytes(b'original')
            target=Path(d)/'song_balanced-master-20261123-183130-414144.wav'
            target.write_bytes(b'other')
            with self.assertRaises(FileExistsError):
                rename_album_master({'file':str(old)}, 'Song', 'balanced')
            self.assertEqual(old.read_bytes(),b'original')
            self.assertEqual(target.read_bytes(),b'other')

if __name__=='__main__':unittest.main()
