"""Cross-platform teardown regression tests; no Windows Qt backend claims."""
import ast
from pathlib import Path
import unittest

UI = Path(__file__).resolve().parents[1] / 'src/mastering_lab/pro_c3_song_preview_ui.py'
STUDIO = UI.with_name('auto_studio_ui.py')

class FakeOutput:
    def __init__(self): self.calls = []
    def setMuted(self, x): self.calls.append(('mute', x))
    def setVolume(self, x): self.calls.append(('volume', x))
    def deleteLater(self): self.calls.append(('delete', None))

class FakePlayer:
    def __init__(self): self.calls=[]
    def stop(self): self.calls.append(('stop', None))
    def setSource(self, x): self.calls.append(('source', x))
    def setAudioOutput(self, x): self.calls.append(('audio', x))
    def deleteLater(self): self.calls.append(('delete', None))

class FakeTimer:
    def __init__(self): self.count=0
    def stop(self): self.count += 1

class FakeButton:
    def setText(self, x): self.text=x

class FakeSelf:
    def __init__(self):
        self._audio_disposed=False
        self._is_closing=False
        self._transport_running=True
        self._start_requested=True
        self._started=True
        self._sync_timer=FakeTimer()
        self.outputs={k:FakeOutput() for k in ('original','gentle','firm')}
        self.players={k:FakePlayer() for k in ('original','gentle','firm')}
        self.loaded={'original','gentle','firm'}
        self.sources={'original':'a.wav'}
        self.play_btn=FakeButton()

class CleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=UI.read_text(encoding='utf-8')
        tree=ast.parse(source)
        wrapper=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SongCompressionPreviewDialog')
        fn=next(n for n in wrapper.body if isinstance(n,ast.FunctionDef) and n.name=='_shutdown_audio')
        module=ast.Module(body=[fn],type_ignores=[])
        ast.fix_missing_locations(module)
        namespace={'QUrl': lambda: 'empty-url'}
        exec(compile(module,str(UI),'exec'),namespace)
        cls.teardown=staticmethod(namespace['_shutdown_audio'])
        cls.source=source
        cls.studio=STUDIO.read_text(encoding='utf8')

    def test_all_three_outputs_muted_before_backend_stop(self):
        obj=FakeSelf();self.teardown(obj)
        for k in ('original','gentle','firm'):
            output=obj.outputs.get(k)
            self.assertIsNone(output)  # mapping cleared
        self.assertFalse(obj._transport_running)
        self.assertTrue(obj._is_closing)
        self.assertTrue(obj._audio_disposed)
        self.assertEqual(obj._sync_timer.count,1)

    def test_outputs_and_players_are_actually_deleted(self):
        obj=FakeSelf(); ps=list(obj.players.values()); outs=list(obj.outputs.values())
        self.teardown(obj)
        for p in ps:
            self.assertEqual(p.calls,[('stop',None),('source','empty-url'),('audio',None),('delete',None)])
        for o in outs:
            self.assertEqual(o.calls,[('mute',True),('volume',0.0),('delete',None)])

    def test_multiple_close_callbacks_do_not_double_destroy(self):
        obj=FakeSelf(); ps=list(obj.players.values()); outs=list(obj.outputs.values())
        self.teardown(obj);self.teardown(obj)
        for p in ps:self.assertEqual(sum(x[0]=='delete' for x in p.calls),1)
        for o in outs:self.assertEqual(sum(x[0]=='delete' for x in o.calls),1)

    def test_all_exit_routes_and_owner_finalizers(self):
        self.assertIn('def done(self, result):',self.source)
        self.assertIn('self.before_close()',self.source)
        self.assertIn('finally:\n            self._shutdown_audio()\n            self.dialog.deleteLater()',self.source)
        self.assertEqual(self.studio.count('dialog._shutdown_audio()'),2)

    def test_switch_stays_continuous_and_stop_reloads(self):
        section=self.source.split('    def switch(self, kind):',1)[1].split('    def _apply_playback_level',1)[0]
        self.assertNotIn('.stop()',section)
        self.assertNotIn('.play()',section)
        self.assertNotIn('setSource(',section)
        self.assertIn('    def stop(self):',self.source)
        self.assertIn('    def _prepare_sources(',self.source)

if __name__=='__main__':unittest.main()

class HermesContextTests(unittest.TestCase):
    def test_context_is_informational_not_an_auto_compressor(self):
        preview=UI.read_text(encoding='utf8')
        studio=STUDIO.read_text(encoding='utf8')
        self.assertIn('studio_context=None',preview)
        self.assertIn('PAS des réglages choisis par Hermes',preview)
        self.assertIn("'reference_used': bool(decision.get('reference_used'))",studio)
        self.assertIn('studio_context=context',studio)
        self.assertNotIn("use_for_hermes':True",preview)
