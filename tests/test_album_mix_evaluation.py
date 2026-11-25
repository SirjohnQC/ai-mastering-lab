import json
import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from mastering_lab.album_mix_evaluation import (
    CANDIDATES, analyze_candidate, choose_candidate, measure_candidates, validate_selection,
)


def _metric(peak=-3.0, corr=0.6):
    return {'sample_peak_dbfs':peak,'sample_peak_clipped':False, 'rms_dbfs':-18,
            'crest_db':15, 'stereo_correlation':corr, 'duration_seconds':5,
            'sample_rate':48000, 'channels':2}


def test_streaming_real_wav(tmp_path):
    rate=48000
    t=np.arange(rate)/rate
    path=tmp_path/'music.wav'
    sf.write(path, np.column_stack((.1*np.sin(2*np.pi*220*t),.1*np.sin(2*np.pi*220*t))), rate)
    m=analyze_candidate(path, block_frames=7000)
    assert -20 < m['sample_peak_dbfs'] < -19
    assert -24 < m['rms_dbfs'] < -22
    assert m['stereo_correlation'] > .999
    assert m['duration_seconds'] == 1


def test_three_variants_and_hermes_selection():
    paths={k:k for k in CANDIDATES}
    selected, report=choose_candidate(paths, analyzer=lambda p:_metric(),
        ask_fn=lambda m:{'selected':'punchy','reason':'Dynamique et crêtes cohérentes.'})
    assert selected=='punchy' and report['mode']=='hermes'
    assert len(report['metrics']) == 3


@pytest.mark.parametrize('bad', [
    {'selected':'outside','reason':'ok'}, {'selected':'balanced','reason':''},
    {'selected':'balanced','reason':'ok','lufs':-14}, {'selected':'balanced','reason':4},
])
def test_invalid_output_falls_back(bad):
    chosen, report=choose_candidate({k:k for k in CANDIDATES},
        analyzer=lambda p:_metric(),ask_fn=lambda m:bad)
    assert chosen=='balanced' and report['mode']=='fallback'


def test_clipping_candidate_falls_back():
    def analyzer(path):
        return _metric(peak=0.1 if path=='punchy' else -2.5)
    chosen, report=choose_candidate({k:k for k in CANDIDATES}, analyzer=analyzer,
        ask_fn=lambda m:{'selected':'punchy','reason':'Choix.'})
    assert chosen=='balanced' and 'crêtes' in report['reason']


def test_negative_stereo_correlation_falls_back():
    chosen, report=choose_candidate({k:k for k in CANDIDATES},
        analyzer=lambda p:_metric(corr=-.8),
        ask_fn=lambda m:{'selected':'punchy','reason':'Choix.'})
    assert chosen=='balanced' and report['mode']=='fallback'


def test_ollama_timeout_falls_back():
    chosen, report=choose_candidate({k:k for k in CANDIDATES},
        analyzer=lambda p:_metric(),ask_fn=lambda m:(_ for _ in ()).throw(TimeoutError('local off')))
    assert chosen=='balanced' and 'TimeoutError' in report['reason']


def test_mismatched_duration_falls_back():
    chosen, report=choose_candidate({k:k for k in CANDIDATES},
        analyzer=lambda p:{**_metric(), 'duration_seconds':5 if p=='balanced' else 6},
        ask_fn=lambda m:{'selected':'balanced','reason':'ok'})
    assert chosen=='balanced' and report['mode']=='fallback'


def test_pipeline_uses_selected_audio_and_manifest(tmp_path, monkeypatch):
    from mastering_lab import album_stem_pipeline as pipeline
    from mastering_lab import stem_mixer, auto_mix_candidates
    folder=tmp_path/'stems'; folder.mkdir()
    for fname in ('Lead Vocals.wav', 'Drums.wav'):
        sf.write(folder/fname, np.zeros((4800,2)), 48000)
    def render(folder, config, out):
        sf.write(out, np.ones((4800,2))*.03, 48000)
        return {'ok':True}
    mastered=[]
    def master(path, target, stop=None):
        mastered.append(path)
        return {'file':str(path), 'status':'qc_pass'}
    result=pipeline.master_stem_folder(folder,tmp_path/'out',render_mix_fn=render,master_fn=master,
        ai_decider=lambda config:(auto_mix_candidates.candidate_configs(config), {'mode':'fallback'}),
        selection_fn=lambda rendered:('vocal-focus',{'mode':'hermes','selected':'vocal-focus','reason':'ok'}))
    assert result['album_selected_candidate']=='vocal-focus'
    assert mastered[0].name=='vocal-focus.wav'
    manifest=json.loads(Path(result['album_candidates_manifest']).read_text())
    assert manifest['selected']=='vocal-focus'
    assert manifest['ai_selection']['mode']=='hermes'
    assert result['album_pipeline'] == pipeline.PIPELINE_ID
