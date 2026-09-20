import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functions" / "common" / "python"))
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def seed_rows() -> list[dict]:
    path = ROOT / "data" / "nsq_seed.jsonl"
    if not path.exists():
        pytest.skip("data/nsq_seed.jsonl missing - run scripts/make_sample_seed.py")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="session")
def index(seed_rows):
    from batchwatch_common.match import NSQIndex

    return NSQIndex(seed_rows)


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    """A LocalStore pointed at a throwaway directory."""
    monkeypatch.setenv("BW_STORE", "local")
    monkeypatch.setenv("BW_LOCAL_DIR", str(tmp_path / "state"))

    from batchwatch_common import store as store_mod

    store_mod.reset_store()
    yield store_mod.get_store()
    store_mod.reset_store()
