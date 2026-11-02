import json
from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def source_config():
    return yaml.safe_load(Path('config/sources/computational.yaml').read_text())


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text()


@pytest.fixture
def fixture_json(fixture_text):
    return lambda name: json.loads(fixture_text(name))


@pytest.fixture(autouse=True)
def no_network(respx_mock, monkeypatch):
    # respx rejects every HTTP request without a registered response.
    monkeypatch.setattr("time.sleep", lambda _: None)
    yield
