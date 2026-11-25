import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pytest
from mastering_lab.ollama_models import installed_models
from mastering_lab.ai_review import AIReviewError

def test_installed_models_local():
    def fake(url, timeout):
        assert url == 'http://127.0.0.1:11434/api/tags'
        return {'models':[{'name':'hermes3:8b'}, {'name':'qwen3-vl:4b'}, {'name':'hermes3:8b'}, {'other':'ignored'}]}
    assert installed_models(transport=fake) == ['hermes3:8b','qwen3-vl:4b']

def test_no_remote_hosts():
    with pytest.raises(AIReviewError):
        installed_models(base_url='http://untrusted.example.com:11434', transport=lambda u,t:{'models':[]})

def test_invalid_response():
    with pytest.raises(AIReviewError):
        installed_models(transport=lambda u,t:{'models':42})
