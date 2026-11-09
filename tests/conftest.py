import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _no_leaked_finish_key():
    """Creating an account makes the `autoapply finish` key in os.environ; keep it from leaking between tests."""
    from autoapply import config
    before = os.environ.pop("AUTOAPPLY_TOKEN", None)
    yield
    os.environ.pop("AUTOAPPLY_TOKEN", None)
    config.FROM_SECRETS.discard("AUTOAPPLY_TOKEN")
    if before is not None:
        os.environ["AUTOAPPLY_TOKEN"] = before
