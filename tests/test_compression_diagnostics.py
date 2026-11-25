import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from mastering_lab.compression_diagnostics import wav_profile, compare_wav_content, analyze_cache, save_reports, read_cached_sources

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root/'settings'/'pro_c3_song_previews'/'test'
        self.folder.mkdir(parents=True)
        sr=48000
        tt=np.arange(96000)/sr
        # Alternating high/low levels to exercise dynamic compression.
        base=(np.where((tt%0.5)<0.25,0.45,0.03)*np.sin(2*np.pi*440*tt)).astype('float32')
        self.sources={}
        for mix in ('balanced','vocal-focus','punchy'):
            self.sources[mix]={}
            for comp in ('original','gentle','firm'):
                audio=base.copy()
                if comp=='gentle':audio*=np.where(np.abs(audio)>.1,.9,1.0)
                if comp=='firm':audio*=np.where(np.abs(audio)>.1,.5,1.0)
                path=self.folder/f'{mix}-{comp}.wav'
                sf.write(path,np.stack([audio,audio],axis=1),sr,subtype='FLOAT')
                self.sources[mix][comp]=str(path)
        manifest={'fingerprint':'abc','result':{'status':'ready','mixes':{m:{'paths':d,'report':{'source_frames':96000}} for m,d in self.sources.items()}}}
        (self.root/'settings/pro_c3_unified_cache.json').write_text(json.dumps(manifest))
    def test_profile_envelope_changes_with_compression(self):
        a=wav_profile(Path(self.sources['balanced']['original']),bins=100)
        b=wav_profile(Path(self.sources['balanced']['firm']),bins=100)
        self.assertEqual(len(a['envelope']),100)
        self.assertGreater(max(a['envelope']),max(b['envelope']))
        self.assertGreater(a['rms_dbfs'],b['rms_dbfs'])
    def test_detects_non_identical(self):
        a=Path(self.sources['balanced']['original']);b=Path(self.sources['balanced']['firm'])
        result=compare_wav_content(a,b,frames=96000)
        self.assertFalse(result['same_samples'])
        self.assertLess(result['rms_delta_db'],-1)
    def test_detects_identical(self):
        a=Path(self.sources['balanced']['original'])
        result=compare_wav_content(a,a,frames=96000)
        self.assertTrue(result['same_samples'])
        self.assertIsNone(result['null_difference_rms_dbfs'])
    def test_cache_nine_and_reports(self):
        result=analyze_cache(self.root,bins=80)
        self.assertEqual(len(result['profiles']),9)
        self.assertEqual(len(result['differences_from_original']),6)
        p,q=save_reports(self.root,result)
        self.assertTrue(p.exists() and q.exists())
        self.assertEqual(json.loads(p.read_text())['kind'],'unified_compression_diagnostics')
    def test_reject_external_manifest_paths(self):
        external=self.root/'some-other-song.wav'
        external.write_bytes(b'fake')
        self.sources['balanced']['firm']=str(external)
        (self.root/'settings/pro_c3_unified_cache.json').write_text(json.dumps({'result':{'status':'ready','mixes':{m:{'paths':v} for m,v in self.sources.items()}}}))
        with self.assertRaises(ValueError):read_cached_sources(self.root)
    def test_reject_mono(self):
        path=self.folder/'mono.wav'
        sf.write(path,np.ones(96000),48000)
        with self.assertRaises(ValueError):wav_profile(path)

if __name__=='__main__':unittest.main()
