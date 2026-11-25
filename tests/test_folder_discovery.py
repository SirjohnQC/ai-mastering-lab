from pathlib import Path
import importlib.util
import pytest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

path = Path(__file__).resolve().parents[1] / 'scripts' / 'reference_eq.py'
spec = importlib.util.spec_from_file_location('folder_reference_eq', path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def test_multiple_source_wavs_one_reference(tmp_path):
    (tmp_path/'source').mkdir(); (tmp_path/'ref').mkdir()
    for name in ['Z.wav','a.WAV','ignore.mp3']:
        (tmp_path/'source'/name).touch()
    (tmp_path/'ref'/'master.wav').touch()
    sources, ref = mod.discover(tmp_path, None, None)
    assert [s.name for s in sources] == ['a.WAV','Z.wav']
    assert ref.name == 'master.wav'

def test_multiple_refs_error(tmp_path):
    (tmp_path/'source').mkdir(); (tmp_path/'ref').mkdir()
    (tmp_path/'source'/'song.wav').touch()
    (tmp_path/'ref'/'a.wav').touch(); (tmp_path/'ref'/'b.wav').touch()
    with pytest.raises(ValueError, match='Multiple reference'):
        mod.discover(tmp_path, None, None)

def test_explicit_reference_override(tmp_path):
    (tmp_path/'source').mkdir(); (tmp_path/'ref').mkdir()
    (tmp_path/'source'/'song.wav').touch()
    (tmp_path/'ref'/'a.wav').touch(); (tmp_path/'ref'/'b.wav').touch()
    sources, ref = mod.discover(tmp_path, None, tmp_path/'ref'/'a.wav')
    assert ref.name == 'a.wav' and len(sources) == 1
