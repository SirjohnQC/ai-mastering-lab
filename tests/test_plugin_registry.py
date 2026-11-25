from pathlib import Path
from mastering_lab.plugin_registry import discover_plugins, suggested_roles, save_settings, read_settings, selected_proq4

def test_scan_nested_and_suggestions(tmp_path):
    vst=tmp_path/'VST3'; (vst/'FabFilter').mkdir(parents=True)
    (vst/'FabFilter'/'FabFilter Pro-Q 4.vst3').write_bytes(b'a')
    (vst/'soothe2.vst3').write_bytes(b'a')
    found=discover_plugins([vst,vst]);assert len(found)==2
    roles=suggested_roles(found)
    assert 'Pro-Q 4' in roles['corrective_eq']
    assert 'soothe' in roles['resonance']

def test_preserve_user_roles(tmp_path):
    path=tmp_path/'settings.json';eq=tmp_path/'FabFilter Pro-Q 4.vst3';eq.write_bytes(b'demo')
    save_settings(path,{'corrective_eq':str(eq),'compression':'custom.vst3'})
    read=read_settings(path)
    assert read['roles']['compression']=='custom.vst3'
    assert read['setup_complete'] is True
    assert selected_proq4(path)==eq

def test_unsupported_eq_is_not_assumed_controllable(tmp_path):
    path=tmp_path/'roles.json'; eq=tmp_path/'OtherEQ.vst3';eq.write_bytes(b'a')
    save_settings(path,{'corrective_eq':str(eq)})
    assert selected_proq4(path) is None
