import tempfile
import unittest
from pathlib import Path
from mastering_lab.pro_c3_diagnostics import inspect_pro_c3

class DiagnosticTests(unittest.TestCase):
    def test_inspect_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); host=root/'host.exe'; vst=root/'FabFilter Pro-C 3.vst3'
            host.write_bytes(b'');vst.mkdir()
            calls=[]
            def mock(h,command,**kwargs):
                calls.append((command,kwargs))
                return {'name':'FabFilter Pro-C 3','parameters':[{'automatable':True},{'automatable':False}]}
            result=inspect_pro_c3(root,host=host,plugin=vst,runner=mock)
            self.assertEqual(result['status'],'inspect_only')
            self.assertEqual(result['automatable_count'],1)
            self.assertEqual(calls[0][0],'inspect')
            self.assertEqual(len(calls),1)
            self.assertNotIn('parameter_changes',calls[0][1])
    def test_wrong_plugin_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host=root/'host.exe';vst=root/'Pro-C 3.vst3'
            host.touch();vst.mkdir()
            with self.assertRaises(ValueError):
                inspect_pro_c3(root,host=host,plugin=vst,runner=lambda *_a,**_k:{'name':'Random Plugin','parameters':[]})
    def test_missing_plugin_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'host.exe').touch()
            with self.assertRaises(FileNotFoundError):
                inspect_pro_c3(root,host=root/'host.exe',plugin=root/'missing.vst3')
