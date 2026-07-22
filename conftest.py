from pathlib import Path
import os, sys, pytest
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
@pytest.fixture(autouse=True)
def isolated_database(tmp_path,monkeypatch):
    monkeypatch.setenv("AI_CIO_DB_PATH",str(tmp_path/"test.db"))
