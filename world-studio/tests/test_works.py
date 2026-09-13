import pytest

from world_studio.repository import StudioError
from world_studio.works import Works, compile_context
from test_atlas import setup_map

BRIEF = {"observer": "银行职员", "period": "改革第一年", "location": "东港", "central_question": "如何保住家人"}


def setup_work(tmp_path):
    repo = setup_map(tmp_path)
    works = Works(repo)
    works.create("book", "东港账簿", "w", repo.head("w"), BRIEF)
    works.create("other", "另一视角", "w", repo.head("w"), BRIEF)
    return repo, works


def save_scene(works, ident, order, time):
    return works.save_artifact("book", works.get("book")["revision"], {"id": ident, "kind": "scene", "title": ident,
        "refs": ["a"], "data": {"reading_order": order, "world_time": time, "pov": "entity_a", "location": "a"}}, ident)


def test_prose_adoption_and_revision_invalidates(tmp_path):
    repo, works = setup_work(tmp_path)
    pinned = repo.head("w")
    save_scene(works, "s1", 1, 1)
    save_scene(works, "s2", 2, 2)
    prose = works.save_prose("book", works.get("book")["revision"], "s1", "她拿走了钥匙。", "draft1")
    assert not works.get("book")["state"]["continuity"]
    continuity = [{"id": "key", "category": "event", "statement": "她拿走钥匙", "evidence": "拿走了钥匙", "refs": ["entity_a"]}]
    adopted = works.adopt("book", prose["revision"], prose["draft"], continuity, "采用正文", "adopt1")
    assert works.adopt("book", prose["revision"], prose["draft"], continuity, "采用正文", "adopt1") == adopted
    context = compile_context(works, "book", "s2")
    assert context["continuity"][0]["id"] == "key"
    assert context["world_revision"] == pinned
    assert not works.get("other")["state"]["continuity"]
    revised = works.save_prose("book", adopted["revision"], "s1", "她没有拿走钥匙。", "draft2")
    with pytest.raises(StudioError, match="quote"):
        works.adopt("book", revised["revision"], revised["draft"], continuity, "采用", "bad")
    assert works.get("book")["revision"] == revised["revision"]
    works.adopt("book", revised["revision"], revised["draft"], [], "采用修订", "adopt2")
    assert not compile_context(works, "book", "s2")["continuity"]
    assert compile_context(works, "book", "s2")["needs_review"] == ["key"]
    assert repo.head("w") == pinned


def test_information_order_and_world_upgrade(tmp_path):
    repo, works = setup_work(tmp_path)
    save_scene(works, "future_first", 1, 20)
    save_scene(works, "flashback", 2, 10)
    draft = works.save_prose("book", works.get("book")["revision"], "future_first", "她知道银行倒闭了。读者看见银行倒闭。", "d")
    works.adopt("book", draft["revision"], draft["draft"], [
        {"id": "character", "category": "character_knowledge", "holder": "entity_a", "statement": "银行倒闭", "evidence": "她知道银行倒闭了"},
        {"id": "reader", "category": "reader_knowledge", "statement": "银行倒闭", "evidence": "读者看见银行倒闭"}], "采用", "adopt")
    assert [c["id"] for c in compile_context(works, "book", "flashback")["continuity"]] == ["reader"]
    place = repo.snapshot("w")["a"]
    place["data"]["x"] = 900
    p = repo.propose("w", "main", repo.head("w"), [{"action": "put", "id": "a", "record": place}], "move")
    target = repo.commit(p["change_set"], "移位")["revision"]
    assert set(works.impact("book", target)["affected"]) >= {"future_first", "flashback"}
    assert compile_context(works, "book", "flashback")["world_revision"] != target
    works.upgrade("book", works.get("book")["revision"], target, "采用新版世界并审查", "upgrade")
    assert compile_context(works, "book", "flashback")["world_revision"] == target
    assert works.get("other")["state"]["world_revision"] != target


def test_scope_and_stale_work(tmp_path):
    repo, works = setup_work(tmp_path)
    base = works.get("book")["revision"]
    save_scene(works, "s", 1, None)
    with pytest.raises(StudioError, match="Work changed"):
        works.save_artifact("book", base, {"id": "new", "kind": "local_entity", "title": "姐姐"}, "stale")
    with pytest.raises(ValueError):
        works.save_artifact("book", works.get("book")["revision"], {"id": "c", "kind": "continuity", "title": "假事实"}, "bad")
    before = repo.head("w")
    works.save_artifact("book", works.get("book")["revision"], {"id": "sister", "kind": "local_entity", "title": "姐姐"}, "sister")
    assert "sister" not in repo.snapshot("w")
    assert repo.head("w") == before
