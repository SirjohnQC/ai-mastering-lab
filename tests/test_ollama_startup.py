import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1]/'src/mastering_lab/ollama_startup.py'
spec = importlib.util.spec_from_file_location('ollama_startup', path)
import sys
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

class FakeProcess:
    def __init__(self, code=None): self.code=code
    def poll(self): return self.code

class StartupTests(unittest.TestCase):
    def test_already_running_does_not_spawn(self):
        def dont_spawn(*a,**kw): self.fail('should not spawn')
        r=mod.ensure_ollama_running(probe=lambda u: True,spawn=dont_spawn)
        self.assertTrue(r.ready)
        self.assertFalse(r.started)
    def test_starts_and_connects(self):
        calls=[False,False,True]
        def probe(_):return calls.pop(0)
        received=[]
        def spawn(args, **kw):
            received.append(args)
            return FakeProcess()
        clockvals=[0,0,0,0]
        r=mod.ensure_ollama_running(probe=probe,executable=lambda:'ollama.exe',spawn=spawn,
            clock=lambda: clockvals.pop(0),sleep=lambda _:None)
        self.assertTrue(r.ready)
        self.assertTrue(r.started)
        self.assertEqual(received,[['ollama.exe','serve']])
    def test_no_executable(self):
        r=mod.ensure_ollama_running(probe=lambda _:False,executable=lambda:None)
        self.assertFalse(r.ready)
    def test_remote_refuses_autostart(self):
        r=mod.ensure_ollama_running(endpoint='http://remote.example:11434',probe=lambda _:False)
        self.assertFalse(r.started)
    def test_startup_exits(self):
        r=mod.ensure_ollama_running(probe=lambda _:False,executable=lambda:'ollama',
           spawn=lambda *a,**kw:FakeProcess(1),clock=lambda:0)
        self.assertFalse(r.ready)
    def test_timeout(self):
        times=iter([0,0,19]);r=mod.ensure_ollama_running(probe=lambda _:False,
            executable=lambda:'ollama',spawn=lambda *a,**kw:FakeProcess(),
            clock=lambda:next(times),sleep=lambda _:None)
        self.assertFalse(r.ready)
        self.assertTrue(r.started)

if __name__=='__main__':unittest.main()
