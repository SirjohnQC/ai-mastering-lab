import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.album_mix_evaluation import validate_selection, choose_candidate

METRICS = {name: {'sample_peak_clipped': False, 'sample_peak_dbfs': -3.,
                  'stereo_correlation': .9, 'rms_dbfs': -16., 'crest_db': 13.}
           for name in ('balanced','vocal-focus','punchy')}

def test_accepts_display_names_and_extraneous_comment():
    result = validate_selection({'selected': 'Vocal Focus', 'reason': 'Bon équilibre mesuré.', 'confidence': .7}, METRICS)
    assert result['selected'] == 'vocal-focus'

def test_accepts_underscore_name():
    assert validate_selection({'selected': 'vocal_focus', 'reason': 'Mesures conformes.'}, METRICS)['selected'] == 'vocal-focus'

def test_long_reason_shortens_without_rejecting_audio():
    result = validate_selection({'selected':'PUNCHY', 'reason':'Variation légère de dynamique. ' * 30}, METRICS)
    assert result['selected'] == 'punchy'
    assert len(result['reason']) <= 240
    assert result['reason'].endswith('…')

def test_unknown_candidate_rejected():
    import pytest
    with pytest.raises(ValueError,match='inconnue'):
        validate_selection({'selected':'Jazz Mix','reason':'OK'}, METRICS)

def test_empty_reason_rejected():
    import pytest
    with pytest.raises(ValueError,match='absente'):
        validate_selection({'selected':'balanced','reason':'  '}, METRICS)

def test_unsafe_peak_still_rejected():
    import pytest
    metrics={k:dict(v) for k,v in METRICS.items()}
    metrics['vocal-focus']['sample_peak_dbfs'] = 0
    with pytest.raises(ValueError,match='crêtes à risque'):
        validate_selection({'selected':'Vocal Focus','reason':'Bon.'}, metrics)

def test_end_to_end_mock_hermes_long_reason_is_accepted():
    result, info = choose_candidate(
        {name: name for name in METRICS},
        analyzer=lambda name: {**METRICS[name], 'duration_seconds': 70., 'sample_rate': 48000},
        ask_fn=lambda measured: {'selected': 'Vocal Focus', 'reason': 'Mesures favorables. ' * 30})
    assert result == 'vocal-focus' and info['mode']=='hermes'
