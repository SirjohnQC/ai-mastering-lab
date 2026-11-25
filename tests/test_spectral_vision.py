import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).parents[1]/'test_env'))
from mastering_lab.spectral_vision import render_spectrogram, render_comparison_spectrograms, local_vision_review
from mastering_lab.mix_evaluator import evaluate_comparison, local_hermes_evaluation

class SpectralVisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.report={'status':'ok','variants':{}}
        sr=48000
        ts=np.arange(sr*2)/sr
        for key,freq in [('balanced',200),('vocal-focus',2000),('punchy',80)]:
            wave=0.15*np.sin(ts*2*np.pi*freq)
            wav=self.root/(key+'.wav')
            sf.write(wav,np.column_stack([wave,wave]),sr)
            self.report['variants'][key]={'wav':str(wav)}
    def test_three_images_and_same_dimensions(self):
        paths=render_comparison_spectrograms(self.report)
        from PIL import Image
        self.assertEqual(set(paths),{'balanced','vocal-focus','punchy'})
        sizes=set()
        for p in paths.values():
            with Image.open(p) as im:
                sizes.add(im.size)
        self.assertEqual(sizes,{(718,298)})
    def test_vision_payload_images_local(self):
        images=render_comparison_spectrograms(self.report)
        calls=[]
        def fake(url,body,timeout):
            calls.append((url,body,timeout))
            return {'message':{'content':json.dumps({'observations':['Some difference'],'limits':['No audio']})}}
        result=local_vision_review(images,transport=fake)
        self.assertIn('Some difference',result['observations'])
        self.assertEqual(len(calls[0][1]['messages'][0]['images']),3)
        self.assertEqual(calls[0][1]['model'],'qwen3-vl:4b')
        self.assertEqual(calls[0][0],'http://127.0.0.1:11434/api/chat')
    def test_hermes_receives_vision_summary(self):
        metrics=evaluate_comparison(self.report)
        def fake(url,body,timeout):
            self.assertEqual(body['model'],'hermes3:8b')
            self.assertIn('spectrogram_vision_observations',body['messages'][1]['content'])
            return {'message':{'content':json.dumps({'summary':'ok','observations':[], 'recommendation':'listen', 'caveats':[]})}}
        report=local_hermes_evaluation(metrics,vision_summary={'observations':['a']},transport=fake)
        self.assertEqual(report['recommendation'],'listen')
    def test_short_file_rejected(self):
        wav=self.root/'short.wav'
        sf.write(wav,np.zeros((100,2)),48000)
        with self.assertRaises(ValueError):render_spectrogram(wav,self.root/'foo.png')

if __name__=='__main__':unittest.main()
