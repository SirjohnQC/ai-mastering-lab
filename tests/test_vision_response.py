import json, sys, tempfile, pathlib, unittest
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
import types
comparison=types.ModuleType('mastering_lab.mix_comparison')
comparison.VARIANT_ORDER=('balanced','vocal-focus','punchy')
comparison.load_comparison=lambda *_: ({},None)
sys.modules['mastering_lab.mix_comparison']=comparison
review=types.ModuleType('mastering_lab.ai_review')
class AIReviewError(Exception): pass
review.AIReviewError=AIReviewError
review._local_endpoint=lambda _: 'http://127.0.0.1:11434/api/chat'
sys.modules['mastering_lab.ai_review']=review
from mastering_lab.spectral_vision import local_vision_review

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.images={key:str(pathlib.Path(self.tmp.name)/f'{key}.png') for key in ('balanced','vocal-focus','punchy')}
        for p in self.images.values(): pathlib.Path(p).write_bytes(b'PNG')
    def test_structured(self):
        data=local_vision_review(self.images,transport=lambda *_: {'message':{'content':json.dumps({'observations':['ok'], 'limits':['not audio']})}})
        self.assertEqual(data['observations'],['ok'])
    def test_plain_text(self):
        data=local_vision_review(self.images,transport=lambda *_: {'message':{'content':'Visual difference in brightness.'}})
        self.assertIn('non structurée',data['observations'][0]); self.assertTrue(data['limits'])
    def test_fenced_json(self):
        data=local_vision_review(self.images,transport=lambda *_: {'message':{'content':'```json\n{"observations":["yes"],"limits":[]}\n```'}})
        self.assertEqual(data['observations'],['yes'])
    def test_empty_text_has_reason(self):
        with self.assertRaisesRegex(AIReviewError,'message vide'):
            local_vision_review(self.images,transport=lambda *_: {'message':{'content':''},'done_reason':'stop'})
    def test_error_response(self):
        with self.assertRaisesRegex(AIReviewError,'model not found'):
            local_vision_review(self.images,transport=lambda *_: {'error':'model not found'})
    def test_empty_http(self):
        class FakeResponse:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return b''
        with patch('mastering_lab.spectral_vision.urlopen',return_value=FakeResponse()):
            with self.assertRaisesRegex(AIReviewError,'HTTP vide'):
                local_vision_review(self.images)
if __name__=='__main__': unittest.main()
