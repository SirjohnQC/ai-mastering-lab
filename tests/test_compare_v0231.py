"""Standalone tests of source/cache safety; real JUCE and Qt require Windows."""
import ast, hashlib, json, tempfile, unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'
UI=(BASE/'auto_studio_ui.py').read_text(encoding='utf-8')
SRC=(BASE/'unified_comparison.py').read_text(encoding='utf-8')
MOD=ast.parse(SRC)
functions={n.name:n for n in MOD.body if isinstance(n,ast.FunctionDef)}
def load_pure():
    code=compile(ast.Module(body=[functions[k] for k in ('session_fingerprint','_cache_valid')],type_ignores=[]),'functions','exec')
    ns={'Path':Path,'hashlib':hashlib,'json':json,'MIXES':('balanced','vocal-focus','punchy'),'COMPRESSIONS':('original','gentle','firm')}
    exec(code,ns)
    return ns
class CompareTests(unittest.TestCase):
    def test_syntax(self):
        for p in (BASE/'unified_comparison.py', BASE/'auto_studio_ui.py',BASE/'version.py'):
            ast.parse(p.read_text(encoding='utf-8'))
    def test_cache_fingerprint_tracks_changes(self):
        ns=load_pure()
        with tempfile.TemporaryDirectory() as tmp:
            paths={k:Path(tmp)/(k+'.wav') for k in ('balanced','vocal-focus','punchy')}
            for p in paths.values():p.write_bytes(b'abc')
            first=ns['session_fingerprint'](paths)
            self.assertEqual(first,ns['session_fingerprint'](paths))
            paths['balanced'].write_bytes(b'different')
            self.assertNotEqual(first,ns['session_fingerprint'](paths))
    def test_cache_rejects_outside_compressed_path(self):
        ns=load_pure()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            inside=root/'settings'/'pro_c3_song_previews'/'x.wav'
            inside.parent.mkdir(parents=True)
            inside.write_bytes(b'data')
            outside=root/'song.wav';outside.write_bytes(b'original')
            result={'status':'ready','mixes':{k:{'report':{'source_frames':1000},'paths':{'original':str(outside),'gentle':str(inside),'firm':str(inside)}} for k in ('balanced','vocal-focus','punchy')}}
            self.assertTrue(ns['_cache_valid'](root,result))
            result['mixes']['punchy']['paths']['firm']=str(outside)
            self.assertFalse(ns['_cache_valid'](root,result))
    def test_single_player_and_waveform(self):
        self.assertIn("player_label = QLabel('Lecteur commun')",SRC)
        self.assertIn('self.waveform = WaveformStrip(self)',SRC)
        self.assertIn('self.unified.mixSelected.connect(self._user_select)',UI)
        self.assertIn('card.hide()',UI)
        self.assertIn('self.legacy_transport.hide()',UI)
    def test_auto_prepare_on_compare(self):
        self.assertIn('QTimer.singleShot(0, self._start_cached_compare)',UI)
        self.assertIn('self.unified.prepare_automatically()',UI)
        self.assertIn('session_fingerprint(self.paths)',SRC)
        self.assertIn('cached=True',SRC)
    def test_no_hidden_master_approval(self):
        node=next(n for n in ast.walk(MOD) if isinstance(n,ast.FunctionDef) and n.name=='master_source')
        body=ast.get_source_segment(SRC,node)
        self.assertIn('self._approved',body)
        self.assertIn('self._sources.get(selected_mix)',body)
    def test_switch_never_restarts_audio(self):
        node=next(n for n in ast.walk(MOD) if isinstance(n,ast.FunctionDef) and n.name=='_switch')
        body=ast.get_source_segment(SRC,node)
        for bad in ('.play(','.stop(','.setSource('):self.assertNotIn(bad,body)
    def test_shutdown_all_nine_players(self):
        node=next(n for n in ast.walk(MOD) if isinstance(n,ast.FunctionDef) and n.name=='_dispose_players')
        body=ast.get_source_segment(SRC,node)
        for word in ('player.stop()', 'player.setSource(QUrl())','output.deleteLater()'):
            self.assertIn(word,body)
if __name__=='__main__':unittest.main()
