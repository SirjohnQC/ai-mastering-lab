from pathlib import Path
import sys
import numpy as np
import soundfile as sf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.fx_chain import prepare_chain

@pytest.mark.parametrize('reported_tail, actual_extra, role, succeeds', [
    (64, 64, 'compression', True),
    (0, 64, 'compression', False),
    (32, 64, 'compression', False),
    (64, 64, 'reverb', False),
    (300, 300, 'compression', False),
    (64, 0, 'compression', False),
    (0, 0, 'compression', True),
])
def test_tail_safety(tmp_path, monkeypatch, reported_tail, actual_extra, role, succeeds):
    # Nonzero signal verifies output wasn't silently dropped or time-shifted.
    base = np.random.default_rng(42).normal(0, .1, size=(1000, 2))
    wav=tmp_path/'stem.wav'; sf.write(wav, base, 48000, subtype='PCM_24')
    host=tmp_path/'host.exe'; host.write_bytes(b'test')
    vst=tmp_path/'plugin.vst3'; vst.write_bytes(b'test')
    import mastering_lab.host as bridge
    def fake(exe, command, **kw):
        if command == 'inspect': return {'status':'ok'}
        sf.write(kw['output_file'], np.vstack([base, np.zeros((actual_extra,2))]), 48000, subtype='PCM_24')
        return {'status':'ok','latency_samples':128,'tail_samples':reported_tail}
    monkeypatch.setattr(bridge,'run_host',fake)
    output=tmp_path/'out.wav'
    if succeeds:
        info=prepare_chain(wav,[{'role':role,'plugin':str(vst)}], output, host)
        rendered, sr=sf.read(output)
        assert sr==48000 and rendered.shape==(1000,2)
        np.testing.assert_allclose(rendered,base,atol=3e-7)
        assert info['stages'][0]['trimmed_declared_tail_samples']==actual_extra
    else:
        with pytest.raises(ValueError):
            prepare_chain(wav,[{'role':role,'plugin':str(vst)}], output, host)
        assert not output.exists()
