"""Check and optionally start a local Ollama server on Windows.

No UI dependency. No polling forever; never start an extra server if one is ready.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

DEFAULT_ENDPOINT = 'http://127.0.0.1:11434'


@dataclass(frozen=True)
class StartupResult:
    ready: bool
    started: bool
    message: str


def is_ready(endpoint: str = DEFAULT_ENDPOINT, *, timeout: float = 0.8) -> bool:
    try:
        with urlopen(endpoint.rstrip('/') + '/api/tags', timeout=timeout) as response:
            return response.status == 200
    except (URLError, HTTPError, OSError, TimeoutError):
        return False


def find_ollama() -> str | None:
    located = shutil.which('ollama')
    if located:
        return located
    local = Path(os.environ.get('LOCALAPPDATA', ''))
    if str(local) != '.':
        for path in (local / 'Programs' / 'Ollama' / 'ollama.exe',
                     local / 'Ollama' / 'ollama.exe'):
            if path.is_file():
                return str(path)
    return None


def ensure_ollama_running(*, endpoint: str = DEFAULT_ENDPOINT,
                          startup_timeout: float = 18.0,
                          probe=is_ready, executable=find_ollama,
                          spawn=subprocess.Popen, sleep=time.sleep,
                          clock=time.monotonic) -> StartupResult:
    """Attempt startup at most once; never terminate or overwrite an existing process."""
    if probe(endpoint):
        return StartupResult(True, False, 'Ollama connecté — serveur déjà actif.')
    # Refuse to start local Ollama for non-local endpoints.
    if endpoint.rstrip('/') not in (DEFAULT_ENDPOINT, 'http://localhost:11434'):
        return StartupResult(False, False, 'Ollama distant indisponible — démarrage local ignoré.')
    cmd = executable()
    if not cmd:
        return StartupResult(False, False, 'Ollama introuvable. Installe Ollama ou configure son chemin.')
    flags = 0
    if os.name == 'nt':
        flags = (getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                 | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    try:
        process = spawn([cmd, 'serve'], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=flags)
    except (OSError, ValueError) as exc:
        return StartupResult(False, False, f'Démarrage Ollama impossible : {exc}')
    deadline = clock() + startup_timeout
    while clock() < deadline:
        if probe(endpoint):
            return StartupResult(True, True, 'Ollama démarré automatiquement — connexion OK.')
        # A competing instance might start: it will be caught by the next probe.
        if process.poll() is not None:
            if probe(endpoint):
                return StartupResult(True, False, 'Ollama connecté — instance existante.')
            return StartupResult(False, False,
                'Ollama a quitté pendant le démarrage. Vérifie les journaux Ollama.')
        sleep(0.5)
    return StartupResult(False, True,
        'Ollama ne répond pas après le démarrage. Mixage DSP disponible; réessaie via Settings → Reconnect Ollama.')
