import json
import zipfile
from pathlib import Path

import pytest

from world_studio.demo import seed_demo
from world_studio.repository import Repository, StudioError
from world_studio.transfer import backup, restore, export_markdown, export_work
from world_studio.works import Works
from world_studio.atlas import Atlas


def test_demo_backup_restore(tmp_path):
    repo = Repository(tmp_path / "original")
    result = seed_demo(repo)
    assert result["route"]["min_days"] == 5
    assert len([r for r in repo.snapshot("northern").values() if r["kind"] == "map"]) == 2
    assert len(result["context"]["continuity"]) == 1
    archive = backup(repo)
    restore(archive["path"], str(tmp_path / "restored"))
    restored = Repository(tmp_path / "restored")
    assert restored.snapshot("northern") == repo.snapshot("northern")
    assert Works(restored).get("ledger") == Works(repo).get("ledger")
    for asset in (repo.root / "assets").iterdir():
        assert (restored.root / "assets" / asset.name).read_bytes() == asset.read_bytes()
    assert export_markdown(restored, "northern")["records"] > 10
    works = Works(restored)
    current = works.get("ledger")
    scene = next(iter(current["state"]["adoptions"]))
    original = export_work(restored, "ledger")
    text = Path(original["path"]).read_text()
    assert original["scenes"] == 1 and current["state"]["world_revision"] in text
    revised = works.save_prose("ledger", current["revision"], scene, "尚未采纳的秘密新稿。", "export-draft")
    assert "尚未采纳的秘密新稿" not in Path(export_work(restored, "ledger")["path"]).read_text()
    works.adopt("ledger", revised["revision"], revised["draft"], [], "采用测试新稿", "export-adopt")
    assert "尚未采纳的秘密新稿" in Path(export_work(restored, "ledger")["path"]).read_text()
    assert Path(export_work(restored, "ledger", current["revision"])["path"]).read_text() == text
    with pytest.raises(StudioError, match="empty"):
        restore(archive["path"], str(tmp_path / "restored"))


def test_corrupt_backup_refused_without_publishing(tmp_path):
    source = Repository(tmp_path / "source")
    seed_demo(source)
    good = backup(source)["path"]
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(good) as original, zipfile.ZipFile(bad, "w") as archive:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "manifest.json":
                manifest = json.loads(data)
                manifest["sha256"]["world.sqlite"] = "0" * 64
                data = json.dumps(manifest).encode()
            archive.writestr(item.filename, data)
    with pytest.raises(StudioError, match="checksum"):
        restore(str(bad), str(tmp_path / "refused"))
    assert not (tmp_path / "refused").exists()


def test_complete_author_workflow(tmp_path):
    repo = Repository(tmp_path / "workflow")
    demo = seed_demo(repo)  # Import, adoption, branch, two maps, two works, plans and prose.
    works, atlas = Works(repo), Atlas(repo)
    sister = works.get("sister")
    draft = atlas.new_draft("northern")
    draft["state"]["capital"]["data"]["x"] = 530
    draft["state"]["bank"]["data"]["x"] = 610
    saved = atlas.save(draft["id"], draft["version"], draft["state"])
    changed_world = atlas.commit(draft["id"], saved["version"], "采用大陆和城市地图修订")["revision"]
    assert repo.head("northern", "federal") == demo["revision"]
    assert repo.snapshot("northern", demo["revision"])["bank"]["data"]["x"] == 500
    old_work = works.get("ledger")
    prose = works.save_prose("ledger", old_work["revision"], "scene1", "“库房的钥匙呢？”沈衡问。陈大人把抽屉推了回去。", "revise")
    adopted = works.adopt("ledger", prose["revision"], prose["draft"],
                          [{"id": "drawer", "category": "event", "statement": "陈大人关上抽屉", "evidence": "把抽屉推了回去"}],
                          "采用修改后的正文", "adopt-revision")
    current = works.get("ledger")
    assert current["state"]["continuity"]["asked_key"]["status"] == "needs_review"
    assert works.get("sister") == sister
    assert "scene1" in works.impact("ledger", changed_world)["affected"]
    assert current["state"]["world_revision"] == demo["revision"]
    works.upgrade("ledger", adopted["revision"], changed_world, "确认升级，逐场复核", "upgrade")
    assert works.get("ledger")["state"]["adoptions"] == current["state"]["adoptions"]
    archive = backup(repo)
    restore(archive["path"], str(tmp_path / "workflow-restored"))
    recovered = Repository(tmp_path / "workflow-restored")
    assert Works(recovered).get("ledger") == works.get("ledger")
    assert recovered.snapshot("northern") == repo.snapshot("northern")
