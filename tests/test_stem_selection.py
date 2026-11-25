from pathlib import Path
import pytest
from mastering_lab.stem_selection import selection_config
from mastering_lab.stem_mixer import parse_tracks

def test_selection_ignores_unselected_mp3(tmp_path):
    a=tmp_path/'0 Lead Vocals.wav'; b=tmp_path/'1 Drums.wav'; extra=tmp_path/'Old Voice.mp3'
    for p in (a,b,extra):p.write_bytes(b'dummy')
    config=selection_config([a,b]); assert len(config['tracks'])==2
    assert config['selection_mode']=='files'
    assert extra.resolve() not in [t.path for t in parse_tracks(config,tmp_path)]

def test_selection_outside_folder_allowed_only_explicitly(tmp_path):
    outer=tmp_path/'external';outer.mkdir();inner=tmp_path/'stems';inner.mkdir()
    p=outer/'guitar.wav';p.write_bytes(b'x')
    config=selection_config([p]);assert parse_tracks(config,inner)[0].path==p.resolve()
    config.pop('selection_mode');
    with pytest.raises(ValueError):parse_tracks(config,inner)

def test_duplicate_rejected(tmp_path):
    p=tmp_path/'voice.wav';p.write_bytes(b'x')
    with pytest.raises(ValueError,match='deux fois'):selection_config([p,p])
