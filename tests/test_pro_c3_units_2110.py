import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("multipoint", Path(__file__).resolve().parents[1]/"src/mastering_lab/pro_c3_multipoint.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_seconds():
    assert module._parse_physical("release", "1.151 sec") == 1151.0
    assert module._parse_physical("release", "1.835 sec") == 1835.0
    assert module._parse_physical("release", "100.0 ms") == 100.0

def test_fail_closed():
    assert module._parse_physical("release", "unknown") is None
    assert module._parse_physical("ratio", "5.0:1") == 5.0
    assert module._parse_physical("threshold", "-16.0 dB") == -16.0

def test_mixed_units_grid():
    points = ["12.90 ms", "36.14 ms", "115.0 ms", "309.5 ms", "655.4 ms", "1.151 sec", "1.835 sec"]
    values = [module._parse_physical("release", p) for p in points]
    assert values == sorted(values)
    assert values[-2:] == [1151., 1835.]
