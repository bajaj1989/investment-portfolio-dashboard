import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402
from core.models import Member  # noqa: E402


@pytest.fixture
def fresh_db(tmp_path):
    db.configure(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with db.session_scope() as s:
        s.add(Member(name="Self", tax_slab=0.3))
        s.add(Member(name="Spouse", tax_slab=0.2))
    yield
    db.get_engine().dispose()
