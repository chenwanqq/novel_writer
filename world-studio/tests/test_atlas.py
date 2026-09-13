import base64
import io

import pytest
from PIL import Image
from starlette.testclient import TestClient

from world_studio.atlas import Atlas, export_svg, route_query
from world_studio.http import create_app
from world_studio.repository import Repository, StudioError
from test_repository import put


def map_changes():
    return [put("map", kind="map", data={"width": 1600, "height": 1000}),
            put("entity_a"), put("entity_b"),
            put("a", kind="place", data={"map": "map", "entity": "entity_a", "x": -20, "y": 100}),
            put("b", kind="place", data={"map": "map", "entity": "entity_b", "x": 500, "y": 200}),
            put("road", kind="route", data={"map": "map", "from": "a", "to": "b", "min_days": 3,
                                           "max_days": 5, "bidirectional": False})]


def setup_map(tmp_path):
    repo = Repository(tmp_path)
    base = repo.create_world("w", "世界")["revision"]
    proposal = repo.propose("w", "main", base, map_changes(), "map")
    repo.commit(proposal["change_set"], "采用地图")
    return repo


def test_draft_conflict_rebase_and_history(tmp_path):
    repo = setup_map(tmp_path)
    atlas = Atlas(repo)
    draft = atlas.new_draft("w")
    original = draft["base"]
    draft["state"]["a"]["data"]["x"] = 99
    saved = atlas.save(draft["id"], 0, draft["state"])
    proposal = repo.propose("w", "main", original, [put("new_entity")], "other")
    repo.commit(proposal["change_set"], "增加实体")
    with pytest.raises(StudioError, match="World changed"):
        atlas.commit(draft["id"], saved["version"], "采用地图")
    assert atlas.draft(draft["id"])["state"]["a"]["data"]["x"] == 99
    reapplied = atlas.rebase(draft["id"], saved["version"])
    atlas.commit(draft["id"], reapplied["version"], "采用地图")
    assert repo.snapshot("w")["a"]["data"]["x"] == 99
    assert repo.snapshot("w", original)["a"]["data"]["x"] == -20
    assert "new_entity" in repo.snapshot("w")


def test_routes_and_background(tmp_path):
    repo = setup_map(tmp_path)
    assert route_query(repo, "w", "a", "b", available_days=1)["timing"] == "impossible"
    assert route_query(repo, "w", "b", "a")["status"] == "unreachable"
    current = repo.snapshot("w")["road"]
    current["data"]["conditions"] = ["关口开放"]
    p = repo.propose("w", "main", repo.head("w"), [{"action": "put", "id": "road", "record": current}], "condition")
    repo.commit(p["change_set"], "采用条件")
    assert route_query(repo, "w", "a", "b")["status"] == "insufficient_information"
    assert route_query(repo, "w", "a", "b", conditions=["关口开放"])["min_days"] == 3
    atlas = Atlas(repo)
    image = io.BytesIO()
    Image.new("RGB", (20, 10)).save(image, "PNG")
    asset = atlas.upload(base64.b64encode(image.getvalue()).decode())
    assert asset["width"] == 20
    assert atlas.background(asset["asset"])["url"].startswith("data:image/png;base64,")
    with pytest.raises(StudioError):
        atlas.background("../secret")


def test_http_auth_and_shared_state(tmp_path):
    repo = setup_map(tmp_path)
    client = TestClient(create_app(repo, "token"), base_url="http://127.0.0.1:8765")
    assert client.post("/api/worlds", json={}).status_code == 403
    headers = {"Authorization": "Bearer token", "Origin": "http://127.0.0.1:8765"}
    assert client.post("/api/worlds", json={}, headers=headers).json()["result"][0]["id"] == "w"
    headers["Origin"] = "https://attacker.example"
    assert client.post("/api/worlds", json={}, headers=headers).status_code == 403


def test_map_commit_rolls_back_world_and_draft_together(tmp_path, monkeypatch):
    repo = setup_map(tmp_path)
    atlas = Atlas(repo)
    draft = atlas.new_draft("w")
    original_head = repo.head("w")
    draft["state"]["a"]["data"]["x"] = 42
    draft = atlas.save(draft["id"], 0, draft["state"])
    original_commit = repo.commit_in_transaction

    def fail_after_world_write(db, proposal, decision):
        original_commit(db, proposal, decision)
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(repo, "commit_in_transaction", fail_after_world_write)
    with pytest.raises(RuntimeError):
        atlas.commit(draft["id"], draft["version"], "采用")
    assert repo.head("w") == original_head
    assert atlas.draft(draft["id"])["committed"] is None
    monkeypatch.setattr(repo, "commit_in_transaction", original_commit)
    result = atlas.commit(draft["id"], draft["version"], "采用")
    assert atlas.commit(draft["id"], draft["version"], "采用") == result


def test_closed_routes_and_same_object_rebase_conflict(tmp_path):
    repo = setup_map(tmp_path)
    atlas = Atlas(repo)
    draft = atlas.new_draft("w")
    draft["state"]["a"]["data"]["x"] = 10
    draft = atlas.save(draft["id"], 0, draft["state"])
    place, road = repo.snapshot("w")["a"], repo.snapshot("w")["road"]
    place["data"]["x"] = 20
    road["data"]["availability"] = "closed"
    changes = [{"action": "put", "id": v["id"], "record": v} for v in (place, road)]
    proposal = repo.propose("w", "main", repo.head("w"), changes, "remote")
    repo.commit(proposal["change_set"], "关闭道路并移动地点")
    assert route_query(repo, "w", "a", "b")["status"] == "unreachable"
    with pytest.raises(StudioError) as error:
        atlas.rebase(draft["id"], draft["version"])
    assert error.value.code == "merge_conflict"
    assert atlas.draft(draft["id"])["state"]["a"]["data"]["x"] == 10


def test_svg_export_pins_revision_and_embeds_background(tmp_path):
    from pathlib import Path
    import xml.etree.ElementTree as ET
    repo = setup_map(tmp_path)
    old = repo.head("w")
    image = io.BytesIO()
    Image.new("RGB", (20, 10)).save(image, "PNG")
    asset = Atlas(repo).upload(base64.b64encode(image.getvalue()).decode())
    map_record = repo.snapshot("w")["map"]
    map_record["data"]["asset"] = asset["asset"]
    p = repo.propose("w", "main", old, [{"action": "put", "id": "map", "record": map_record}], "bg")
    repo.commit(p["change_set"], "采用底图")
    text = Path(export_svg(repo, "w", "map")["path"]).read_text()
    ET.fromstring(text)
    assert "data:image/png;base64," in text
    assert "data:image" not in Path(export_svg(repo, "w", "map", old)["path"]).read_text()
