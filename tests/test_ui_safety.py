import ast
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STEM=ROOT/'src/mastering_lab/stem_plus_ui.py'
DESKTOP=ROOT/'src/mastering_lab/desktop.py'

def test_version_single_source():
    spec=importlib.util.spec_from_file_location('aml_version',ROOT/'src/mastering_lab/version.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.APP_VERSION=='0.10.1'
    assert 'v0.10.1' in module.window_title()
    assert 'window_title()' in DESKTOP.read_text(encoding='utf8')

def test_stem_actions_have_guards():
    tree=ast.parse(STEM.read_text(encoding='utf8'))
    methods={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    for name in ('toggle_play','save_config','prepare_eq','export_to_mastering','render_mix','fx_suggest_all','prepare_fx'):
        assert '_require_stems' in ast.get_source_segment(STEM.read_text(encoding='utf8'),methods[name])

def test_states_disable_and_restore():
    src=STEM.read_text(encoding='utf8')
    assert 'def refresh_action_availability' in src
    assert 'widget.setEnabled(ready)' in src
    assert 'self.config=config\n        for i,entry' in src
    assert 'self.refresh_action_availability()' in src

def test_version_not_hardcoded_in_desktop():
    assert "v0.9.5 STEM+" not in DESKTOP.read_text(encoding='utf8')

def test_desktop_missing_inputs_handled():
    src=DESKTOP.read_text(encoding='utf8')
    assert 'def refresh_mastering_actions' in src
    assert "has_source=self.current_source() is not None" in src
    assert "has_reference=self.ref.currentData() is not None" in src
