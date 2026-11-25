"""Offline tests for model settings logic (no PySide6 or Ollama required)."""
import ast, base64, json, tempfile, unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]/'src'/'mastering_lab'/'ai_settings_ui.py'
NAMES={'read_ai_preferences','save_ai_preferences','test_ollama'}
tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
namespace={'Path':Path, 'json':json, 'base64':base64, 'DEFAULT_TEXT':'hermes3:8b',
           'DEFAULT_VISION':'qwen3-vl:4b', 'ollama_request':lambda *a, **kw: None}
code=compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in NAMES],type_ignores=[]), str(SOURCE),'exec')
exec(code,namespace)

class TestSettings(unittest.TestCase):
    def test_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=namespace['read_ai_preferences'](Path(tmp))
            self.assertEqual(c['model'],'hermes3:8b')
            self.assertEqual(c['vision_model'],'qwen3-vl:4b')
    def test_save_preserves_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'settings'/'ai_review.json';p.parent.mkdir()
            p.write_text('{"other":true,"model":"old"}',encoding='utf-8')
            namespace['save_ai_preferences'](Path(tmp),'hermes3:8b','qwen3-vl:8b')
            c=json.loads(p.read_text(encoding='utf-8'))
            self.assertEqual(c['vision_model'],'qwen3-vl:8b')
            self.assertTrue(c['other'])
    def test_connection_and_model_checks(self):
        def fake(url,body=None,timeout=0):
            if url.endswith('/api/tags'):return {'models':[{'name':'hermes3:8b'},{'name':'qwen3-vl:4b'}]}
            self.assertEqual(body['stream'],False)
            return {'message':{'content':'OK'}}
        for target,model in [('server',None),('text','hermes3:8b'),('vision','qwen3-vl:4b')]:
            self.assertIn('OK',namespace['test_ollama'](target,model,requester=fake))
    def test_absent_model_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'absent'):
            namespace['test_ollama']('text','wrong',requester=lambda *a,**kw:{'models':[]})

if __name__=='__main__':unittest.main()
