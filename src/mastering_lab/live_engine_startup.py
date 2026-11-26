"""Bounded startup check for the native JUCE Live Stem Engine.

Runs once in the desktop startup splash before the user opens an album song.
A failed check never blocks the existing offline production workflow.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def locate_engine(root):
    root=Path(root)
    candidates=(
        root/'native'/'build'/'frankenstem-live_artefacts'/'Release'/'frankenstem-live.exe',
        root/'native'/'build'/'frankenstem-live_artefacts'/'frankenstem-live.exe',
        root/'native'/'build'/'Release'/'frankenstem-live.exe',
    )
    return next((p for p in candidates if p.is_file()),None)


def check_engine(root, *, timeout=5):
    """Return a user-readable result, never crash or wait indefinitely."""
    exe=locate_engine(root)
    if exe is None:
        return {'ready':False,'reason':
            'Live Engine non compilé. Compile frankenstem-live avec CMake; '
            'Auto Produce reste disponible.'}
    try:
        result=subprocess.run(
            [str(exe),'--probe'],capture_output=True,text=True,
            encoding='utf-8',errors='replace',timeout=timeout,check=False)
    except subprocess.TimeoutExpired:
        return {'ready':False,'reason':
            'Le test JUCE a dépassé 5 secondes : vérifie le périphérique audio '
            'Windows, puis relance FRANKENSTEM.'}
    except (OSError,ValueError) as exc:
        return {'ready':False,'reason':f'Exécutable Live Engine indisponible : {exc}'}
    messages=[]
    for line in result.stdout.splitlines():
        try:
            data=json.loads(line)
        except (json.JSONDecodeError,TypeError):
            continue
        if isinstance(data,dict):
            messages.append(data)
    for data in messages:
        if data.get('status')=='probe_ok' and result.returncode==0:
            return {'ready':True,'reason':
                f'JUCE prêt · {data.get("device","sortie audio")} '
                f'({data.get("sample_rate","?")} Hz)'}
    problem=next((m.get('message','') for m in messages
                  if m.get('status')=='error'),None)
    return {'ready':False,'reason':str(problem or
        f'Le moteur JUCE ne répond pas au contrôle de démarrage '
        f'(code {result.returncode}). Reconstruis frankenstem-live.')}
