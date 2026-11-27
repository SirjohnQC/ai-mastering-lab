import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from mastering_lab.preference_learning import save_choice, preference_context, preference_path, load_preferences
from mastering_lab.mix_rating_ui import MixRatingPanel
from mastering_lab.mix_compare_ui import _Gen2Worker

METRICS = {key: {'rms_dbfs': -18., 'sample_peak_dbfs': -3., 'crest_db': 15., 'stereo_correlation': .9}
           for key in ('balanced', 'vocal-focus', 'punchy')}
RATINGS = {'balanced': 2, 'vocal-focus': 5, 'punchy': 1}


def test_ratings_upsert_and_context(tmp_path):
    path = preference_path(tmp_path)
    for _ in range(2):
        assert save_choice(path, selected='vocal-focus', metrics=METRICS,
                           ratings=RATINGS, session='private/path/session.json', song='Private title') == 1
    context = preference_context(path)
    assert context['rated_examples'][0]['ratings'] == RATINGS
    assert 'Private title' not in json.dumps(context)
    assert 'private/path' not in json.dumps(context)
    assert context['variant_counts']['vocal-focus'] == 1


@pytest.mark.parametrize('ratings', [{}, {**RATINGS, 'punchy': True}, {**RATINGS, 'punchy': 6}, {**RATINGS, 'punchy': 0}])
def test_invalid_ratings_never_write(tmp_path, ratings):
    with pytest.raises(ValueError):
        save_choice(preference_path(tmp_path), selected='vocal-focus', metrics=METRICS, ratings=ratings)
    assert not preference_path(tmp_path).exists()


def test_scores_reach_generator_and_fallback_is_honest(tmp_path):
    save_choice(preference_path(tmp_path), selected='vocal-focus', metrics=METRICS, ratings=RATINGS)
    worker = _Gen2Worker('report.json', 'test-model', project_root=tmp_path)
    results = []
    worker.finished.connect(lambda result, error: results.append((result, error)))
    with patch('mastering_lab.auto_mix_gen2.read_session'), \
         patch('mastering_lab.mix_evaluator.evaluate_comparison', return_value={'metrics': METRICS}), \
         patch('mastering_lab.auto_mix_gen2.model_proposal', return_value={'source': 'hermes'}) as proposal:
        worker.run()
        context = proposal.call_args.args[0]['user_preferences']
        assert context['rated_examples'][0]['ratings'] == RATINGS
        assert results[-1][0]['preferences_used'] is True
        proposal.side_effect = RuntimeError('offline')
        worker.run()
        assert results[-1][0]['preferences_used'] is False
        assert results[-1][0]['source'] == 'fallback'


def test_panel_requires_explicit_scores_and_resets(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = MixRatingPanel(tmp_path)
    panel.set_language('en')
    panel.set_session(tmp_path / 'report.json', METRICS)
    assert panel.save() is False
    assert not preference_path(tmp_path).exists()
    for key, value in RATINGS.items():
        panel.scores[key].setValue(value)
    assert panel.save() is True
    assert panel.favorite == 'vocal-focus'
    assert load_preferences(preference_path(tmp_path))['examples'][0]['ratings'] == RATINGS
    panel.scores['balanced'].setValue(3)
    assert panel.save() is True
    assert len(load_preferences(preference_path(tmp_path))['examples']) == 1
    panel.reset()
    assert all(score.value() == 0 for score in panel.scores.values())
    assert not panel.save_button.isEnabled()
    panel.close()


def test_cached_compression_does_not_hide_new_generation(tmp_path):
    from mastering_lab.desktop import MainWindow
    app = QApplication.instance() or QApplication([])
    with patch('mastering_lab.stem_plus_ui.StemPlusPage._restore_previous_selection'), \
         patch('mastering_lab.auto_studio_ui.AutoStudioPage._restore'):
        window = MainWindow(tmp_path)
        page = window.auto_studio
        player = MagicMock()
        player._comparison_source = tmp_path / 'new.json'
        player._gen2_thread = None
        player._pos = 0; player.rate = 48000; player.frames = 48000
        player._fmt.return_value = '00:00'
        player.paths = {'balanced': 'new.wav'}
        page._player = player
        page._current_source = str(tmp_path / 'old.json')
        page.unified._files = {('balanced', 'original'): 'old.wav'}
        with patch.object(page.unified, 'set_sources') as sources, \
             patch.object(page, '_load_waveforms'), patch.object(page, '_select'), \
             patch.object(page, '_start_ai_evaluation'), patch.object(page, '_start_cached_compare'):
            page._sync_player()
            sources.assert_called_once()
            assert page._report == player._comparison_source.resolve()
        page.unified._files = {}
        page._player = None
        window.close()


def test_eq_handoff_is_explicit_and_never_auto_renders(tmp_path):
    from mastering_lab.desktop import MainWindow
    import numpy as np
    import soundfile as sf
    app = QApplication.instance() or QApplication([])
    dry, wet = tmp_path / 'dry.wav', tmp_path / 'corrected.wav'
    for file in (dry, wet):
        sf.write(file, np.zeros((480, 2)), 48000)
    with patch('mastering_lab.stem_plus_ui.StemPlusPage._restore_previous_selection'), \
         patch('mastering_lab.auto_studio_ui.AutoStudioPage._restore'):
        window = MainWindow(tmp_path)
        page = window.auto_studio
        page.unified._sources = {'balanced': dry}
        page._fx_source = str(dry.resolve())
        page._fx_audition = str(wet.resolve())
        with patch.object(page.unified, 'master_source', return_value=dry), \
             patch.object(page, '_start_master') as render:
            page._prepare_mastering_navigation()
            assert page._master_input == dry
            page._approve_eq_master()
            assert page._master_input == wet.resolve()
            assert 'approved EQ' in page._master_mix_variant
            render.assert_not_called()
            page._reset_ai_fx()
            assert page._approved_eq_source is None
        window.close()
