"""Local-only Ollama model discovery and model-name validation."""
from __future__ import annotations
import json
from urllib.request import Request, urlopen
from urllib.error import URLError
from .ai_review import _local_endpoint, AIReviewError


def installed_models(base_url: str = 'http://127.0.0.1:11434', *, timeout: float = 3, transport=None) -> list[str]:
    """Query local /api/tags. Return installed model names without inventing entries."""
    endpoint = _local_endpoint(base_url).removesuffix('/api/chat') + '/api/tags'
    if transport is None:
        def transport(url, seconds):
            with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=seconds) as response:
                return json.loads(response.read(1_000_000))
    try:
        payload = transport(endpoint, timeout)
        models = payload['models']
        if not isinstance(models, list):
            raise ValueError('models must be a list')
        found = set()
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get('name') or model.get('model')
            if isinstance(name, str) and name.strip() and len(name) <= 120:
                found.add(name.strip())
        return sorted(found, key=str.casefold)
    except Exception as exc:
        raise AIReviewError(f'Impossible de lire les modèles Ollama: {exc}') from exc
