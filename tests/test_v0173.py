"""Regression tests for Auto Master click-only navigation and processed output guard."""
import ast
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / 'src/mastering_lab/auto_studio_ui.py'


def _methods(*names):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    widget = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AutoStudioPage')
    extracted = [n for n in widget.body if isinstance(n, ast.FunctionDef) and n.name in names]
    module = ast.Module(body=extracted, type_ignores=[])
    ns = {'Path': Path, 'QMessageBox': SimpleNamespace(warning=lambda *a: None)}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), 'exec'), ns)
    return ns


class Label:
    def __init__(self, value=''):
        self.value = value
        self.enabled = None
    def setText(self, value): self.value = value
    def setEnabled(self, enabled): self.enabled = enabled


class Dummy:
    pass


def setup(tmp_path):
    funcs = _methods('_master_key', '_master_is_processed', '_update_master_button', '_open_master_stage', '_continue_mastering')
    x = Dummy()
    x._master_key = lambda: funcs['_master_key'](x)
    x._master_is_processed = lambda: funcs['_master_is_processed'](x)
    x._update_master_button = lambda: funcs['_update_master_button'](x)
    x._continue_mastering = lambda: funcs['_continue_mastering'](x)
    source = tmp_path / 'balanced.wav'
    source.write_bytes(b'synthetic wav')
    x._master_input = source
    x._master_mix_variant = 'balanced'
    x._song_title_for_export = lambda: 'Test Song'
    x._master_worker = None
    x._master_result = None
    x._master_completed_key = None
    x._master_running_key = None
    x.master_run = Label()
    x.master_status = Label()
    x.master_description = Label()
    x.master_open = SimpleNamespace(hide=lambda: None)
    x.master_listen = SimpleNamespace(hide=lambda: None)
    x.master_report = Label()
    x.master_progress = SimpleNamespace(setValue=lambda v: None)
    x._stop = lambda: None
    x._selected = 'balanced'
    x._selected_mix_path = lambda: source
    x._go = lambda stage: setattr(x, 'stage', stage)
    return x, funcs


def test_open_stage_does_not_launch_master(tmp_path):
    x, methods = setup(tmp_path)
    x._start_master = lambda: (_ for _ in ()).throw(AssertionError('Master ran during navigation'))
    methods['_open_master_stage'](x)
    assert x.stage == 3
    assert x.master_run.enabled is True


def test_button_disabled_for_completed_existing_output(tmp_path):
    x, _ = setup(tmp_path)
    outfile = tmp_path / 'master.wav'
    outfile.write_bytes(b'mastered audio')
    x._master_result = {'file': str(outfile)}
    x._master_completed_key = x._master_key()
    x._update_master_button()
    assert x.master_run.enabled is False
    assert 'DÉJÀ CRÉÉ' in x.master_run.value


def test_changing_title_or_variant_reenables_button(tmp_path):
    x, _ = setup(tmp_path)
    output = tmp_path / 'master.wav'
    output.write_bytes(b'audio')
    x._master_result = {'file': str(output)}
    x._master_completed_key = x._master_key()
    x._master_mix_variant = 'punchy'
    x._update_master_button()
    assert x.master_run.enabled is True
    x._master_mix_variant = 'balanced'
    x._song_title_for_export = lambda: 'A new title'
    x._update_master_button()
    assert x.master_run.enabled is True


def test_deleted_output_allows_retry(tmp_path):
    x, _ = setup(tmp_path)
    x._master_result = {'file': str(tmp_path/'missing.wav')}
    x._master_completed_key = x._master_key()
    x._update_master_button()
    assert x.master_run.enabled is True


def test_source_change_allows_retry(tmp_path):
    x, _ = setup(tmp_path)
    outfile = tmp_path / 'master.wav'
    outfile.write_bytes(b'audio')
    x._master_result = {'file': str(outfile)}
    x._master_completed_key = x._master_key()
    x._master_input.write_bytes(b'changed contents')
    x._update_master_button()
    assert x.master_run.enabled is True


def test_no_automatic_start_timer_or_trigger():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AutoStudioPage')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_continue_mastering')
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == '_start_master' for n in ast.walk(fn))
    assert 'QTimer.singleShot' not in ast.get_source_segment(SOURCE.read_text(), fn)
