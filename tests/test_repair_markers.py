from pathlib import Path
import csv
import json
import pytest
from mastering_lab.repair_markers import (project_id, markers_path, format_time, validate_marker,
                                           write_markers, read_markers, export_csv)


def test_times():
    assert format_time(72891) == '01:12.891'


def test_validation():
    sample = dict(start_ms=72000, end_ms=80000, issue='metallic_voice', action='overdub_vocal')
    assert validate_marker(sample, 100000)['start_ms'] == 72000
    for bad in (dict(sample, end_ms=72000), dict(sample, start_ms=-1), dict(sample, action='unicorn')):
        with pytest.raises(ValueError): validate_marker(bad)
    with pytest.raises(ValueError): validate_marker(sample, 79000)


def test_project_names_do_not_collide(tmp_path):
    a=tmp_path/'one'/'song.wav'; b=tmp_path/'two'/'song.wav'
    assert project_id(a)!=project_id(b)


def test_roundtrip_and_csv(tmp_path):
    source=tmp_path/'song.wav'
    items=[dict(start_ms=12000,end_ms=17000,issue='guitar_noise',action='overdub_guitar',notes='buzz',take_path=''),
           dict(start_ms=1000,end_ms=5000,issue='sibilance',action='review',notes='s',take_path='')]
    p=write_markers(tmp_path,source,items,30000)
    assert p.exists()
    got=read_markers(tmp_path,source)
    assert [x['start_ms'] for x in got] == [1000,12000]
    with export_csv(tmp_path,source).open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.reader(f))
    assert rows[2][0]=='00:12.000'


def test_reject_cross_source(tmp_path):
    a=tmp_path/'a.wav'; b=tmp_path/'b.wav'
    p=write_markers(tmp_path,a,[])
    payload=json.loads(p.read_text());payload['source']=str(b.resolve());p.write_text(json.dumps(payload))
    with pytest.raises(ValueError):read_markers(tmp_path,a)
