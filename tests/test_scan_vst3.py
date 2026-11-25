from pathlib import Path
from mastering_lab.scan_vst3 import discover

def test_discover_bundle_and_file(tmp_path: Path):
    (tmp_path / 'Pro-Q 4.vst3').mkdir()
    (tmp_path / 'Test.vst3').write_bytes(b'')
    (tmp_path / 'ignore.txt').write_text('no')
    results = discover([tmp_path])
    assert [r['name'] for r in results] == ['Pro-Q 4', 'Test']
    assert results[0]['type'] == 'bundle'
