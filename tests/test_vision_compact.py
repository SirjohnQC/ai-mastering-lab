"""Tests for the bounded single-image Ollama vision call."""
from pathlib import Path
import tempfile
import json
import sys
import types
import importlib.util
from PIL import Image

# Load our module without requiring Qt, which is not installed in CI.
ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'
pkg = types.ModuleType('mastering_lab')
pkg.__path__ = [str(ROOT)]
sys.modules['mastering_lab'] = pkg
for name in ('mix_comparison', 'ai_review'):
    # Existing app dependencies are injected for isolated logic tests.
    mod = types.ModuleType('mastering_lab.'+name)
    if name == 'mix_comparison':
        mod.VARIANT_ORDER = ('balanced','vocal-focus','punchy')
        mod.load_comparison = lambda _: ({},None)
    else:
        mod._local_endpoint = lambda url: url+'/api/chat'
        mod.AIReviewError = type('AIReviewError',(Exception,),{})
    sys.modules[mod.__name__] = mod
spec=importlib.util.spec_from_file_location('mastering_lab.spectral_vision',ROOT/'spectral_vision.py')
spectral=importlib.util.module_from_spec(spec)
spec.loader.exec_module(spectral)

def paths(tmp_path):
    result={}
    for i,key in enumerate(('balanced','vocal-focus','punchy')):
        p=tmp_path/(key+'.png')
        Image.new('RGB',(700,250),(i*60,20,50)).save(p)
        result[key]=str(p)
    return result

def test_one_image_only(tmp_path):
    seen=[]
    def mock(url,body,seconds):
        seen.append(body)
        return {'message':{'content':'Les trois images sont proches.'},'done_reason':'stop'}
    result=spectral.local_vision_review(paths(tmp_path),transport=mock)
    assert len(seen)==1
    assert len(seen[0]['messages'][0]['images'])==1
    assert seen[0]['think'] is False
    assert result['observations']

def test_thinking_is_not_content(tmp_path):
    def mock(url,body,seconds):
        return {'message':{'content':'','thinking':'very long reasoning'},'done_reason':'length'}
    try:
        spectral.local_vision_review(paths(tmp_path),transport=mock)
        raise AssertionError('empty content must fail explicitly')
    except spectral.AIReviewError as exc:
        assert '3072 tokens' in str(exc)

def test_json_answer(tmp_path):
    def mock(url,body,seconds):
        return {'message':{'content':json.dumps({'observations':['Plus de médiums'],'limits':['Image seule']})},'done_reason':'stop'}
    assert spectral.local_vision_review(paths(tmp_path),transport=mock)['observations']==['Plus de médiums']
