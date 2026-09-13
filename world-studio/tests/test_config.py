import pytest
from pathlib import Path
from world_studio.config import contained, data_path


def test_data_location_and_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLD_STUDIO_DATA", str(tmp_path))
    assert data_path() == tmp_path
    assert contained(tmp_path, "sources/a.txt") == tmp_path / "sources/a.txt"
    with pytest.raises(ValueError, match="escapes"):
        contained(tmp_path, "../private.txt")
    with pytest.raises(ValueError, match="outside"):
        data_path(Path(__file__).resolve().parents[1] / "data")
