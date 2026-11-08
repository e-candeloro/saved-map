import os
import tempfile

# every test session works in a throwaway data folder; set before savedmap is imported
os.environ["SAVEDMAP_DATA"] = tempfile.mkdtemp(prefix="savedmap-test-")

import pytest  # noqa: E402

from savedmap import db  # noqa: E402


@pytest.fixture
def con():
    db.DB_PATH.unlink(missing_ok=True)
    c = db.connect()
    yield c
    c.close()
