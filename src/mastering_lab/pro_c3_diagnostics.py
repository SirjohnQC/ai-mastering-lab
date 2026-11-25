"""Read-only Pro-C 3 plugin probe. No parameter writes, state changes, or audio render."""
from pathlib import Path


def inspect_pro_c3(root, *, host=None, plugin=None, runner=None):
    root = Path(root).resolve()
    host = Path(host or root / 'native/build/mastering-host_artefacts/Release/mastering-host.exe').resolve()
    plugin = Path(plugin or 'C:/Program Files/Common Files/VST3/FabFilter/FabFilter Pro-C 3.vst3').resolve()
    if not host.is_file():
        raise FileNotFoundError('JUCE mastering-host.exe introuvable. Aucun traitement lancé.')
    if not plugin.exists() or plugin.suffix.lower() != '.vst3':
        raise FileNotFoundError('FabFilter Pro-C 3.vst3 introuvable. Aucun traitement lancé.')
    if runner is None:
        from .host import run_host
        runner = run_host
    info = runner(host, 'inspect', plugin=plugin, timeout=90)
    name = str(info.get('name', ''))
    if 'pro-c 3' not in name.lower():
        raise ValueError(f'Plugin inattendu : {name!r}. Aucun traitement lancé.')
    params = info.get('parameters', [])
    if not isinstance(params, list):
        raise ValueError('Métadonnées de paramètres invalides.')
    return {'plugin': name, 'parameters_count': len(params),
            'automatable_count': sum(bool(p.get('automatable')) for p in params if isinstance(p, dict)),
            'status': 'inspect_only',
            'note': 'Pro-C 3 détecté. Paramètres NON calibrés : aucune compression automatique.'}
