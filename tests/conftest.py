"""pytest 閰嶇疆 + fixture"""

import pytest

from sump.config import Config


@pytest.fixture
def config():
    return Config()