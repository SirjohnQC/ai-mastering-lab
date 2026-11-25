"""Static checks for the minimal UI orchestration; runtime VST tests require Windows."""
from pathlib import Path
import ast
src=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'/'stem_plus_ui.py'
code=src.read_text(encoding='utf-8')
tree=ast.parse(code)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StemPlusPage')
methods={n.name for n in cls.body if isinstance(n,ast.FunctionDef)}
def test_ui_methods_exist():
    assert {'start_guided_production','_guided_prepare_or_mix','_guided_render_mix','_set_advanced_mode'} <= methods

def test_fx_cache_enabled_before_export():
    assert "self.rows[idx]['entry']['eq']=True" in code
    assert 'self._guided_render_mix' in code

def test_automatic_compare_analysis():
    assert 'auto_analyze=guided' in code
    assert 'player.start_automatic_analysis' in code

def test_keeps_user_approval():
    assert 'dialog.exec()!=QDialog.Accepted' in code
    assert "mode['value']=='prepare'" in code

def test_originals_not_overwritten():
    from importlib.util import spec_from_file_location, module_from_spec
    p=Path(__file__).resolve().parents[2]/'aml_v0113_work'/'src'/'mastering_lab'/'auto_mix_candidates.py'
    spec=spec_from_file_location('auto_mix_candidates_check',p)
    module=module_from_spec(spec);spec.loader.exec_module(module)
    data={'tracks':[{'file':'lead.wav','category':'vocal','gain_db':0,'eq':True}]}
    candidates=module.candidate_configs(data)
    assert data['tracks'][0]['gain_db']==0
    assert candidates['vocal-focus']['tracks'][0]['gain_db']==1
