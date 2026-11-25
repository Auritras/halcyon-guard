import pytest

from halcyon import store


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = store.connect(path)
    store.reset(conn)
    conn.close()
    return path


@pytest.fixture
def conn(db_path):
    c = store.connect(db_path)
    yield c
    c.close()
