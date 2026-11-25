from mastering_lab.pro_c3_multipoint import GRIDS, INDICES, EXPECTED, validate_probes, summarize
import pytest


def sample():
    readings = []
    for role, idx in INDICES.items():
        for n in GRIDS:
            if role == 'threshold': text = f'{-60 + n * 60:.2f} dB'
            elif role == 'ratio': text = f'{1 + n * 9:.2f}:1'
            elif role == 'attack': text = f'{n * 50 + .1:.3f} ms'
            else: text = f'{n * 500 + 1:.3f} ms'
            readings.append({'index': idx, 'name': EXPECTED[role], 'normalized': n, 'display_text': text})
    return {'name': 'FabFilter Pro-C 3', 'read_only': True, 'method': 'getText', 'probe_points': readings}


def test_all_four_roles_and_not_ready():
    report = validate_probes(sample())
    assert len(report['probe_points']) == 4
    assert all(v == 'text_grid_plausible' for v in report['display_mapping_status'].values())
    assert report['ready_to_render'] is False
    assert report['mapping_verified'] is False
    assert '0.050' in summarize(report)


def test_requires_explicit_read_only():
    s=sample(); s['read_only']=False
    with pytest.raises(ValueError): validate_probes(s)


def test_wrong_parameter_index_rejected():
    s=sample(); s['probe_points'][0]['index']=2
    with pytest.raises(ValueError): validate_probes(s)


def test_missing_points_are_not_verified():
    s=sample(); s['probe_points'].pop()
    result=validate_probes(s)
    assert result['display_mapping_status']['release'] == 'insufficient_points'
    assert result['ready_to_render'] is False


def test_previously_inspected_indices_must_match():
    s=sample()
    baseline={'candidates': {role:[{'index':idx}] for role,idx in INDICES.items()}}
    assert validate_probes(s, baseline=baseline)['read_only']
    baseline['candidates']['ratio'][0]['index']=99
    with pytest.raises(ValueError): validate_probes(s, baseline=baseline)
