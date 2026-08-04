"""pytest 配置与 fixture"""

import pytest

from sump.config import Config


@pytest.fixture
def config():
    return Config()
