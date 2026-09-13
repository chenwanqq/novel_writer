import json
import pytest
from world_studio.ingestion import Ingestion, parse_units, search
from world_studio.repository import Repository, StudioError
from test_repository import put


def test_import_resume_provenance_and_chinese(tmp_path):
    r = Repository(tmp_path)
    base = r.create_world("w", "世界")["revision"]
    i = Ingestion(r)
    text = "议会十二席。假设二十四席呢？最终仍采用十二席。"
    source = i.ingest("w", "议会.md", text, "chat")
    assert i.ingest("w", "重复.md", text, "chat")["duplicate"]
    assert not i.list("w")[0]["complete"]
    assert i.read(source["source_id"], "document", max_chars=5)["next_start"] == 5
    record = put("council", sources=[{"source_id": source["source_id"], "locator": "document"}])
    p = r.propose("w", "main", base, [record], "p")
    i.reviewed(source["source_id"], "document", "已读取全文，二十四席未采用", [p["change_set"]])
    assert Ingestion(Repository(tmp_path)).list("w")[0]["complete"]
    r.commit(p["change_set"], "采用十二席")
    assert search(r, "w", "议会")["total"] == 1


def test_chat_branches_and_unknown_formats():
    def node(parent, text):
        return {"parent": parent, "message": {"author": {"role": "user"}, "content": {"parts": [text]}}}
    obj = {"id": "c", "mapping": {"root": node(None, "初始"), "a": node("root", "十二席"), "b": node("root", "二十四席")}}
    units = parse_units("conversations.json", json.dumps([obj]))
    assert len(units) == 2
    assert all(not ("十二席" in u["text"] and "二十四席" in u["text"]) for u in units)
    with pytest.raises(StudioError):
        parse_units("unknown.json", '{"messages": []}')
    obj["mapping"]["cycle"] = node("cycle", "bad")
    with pytest.raises(StudioError):
        parse_units("cyclic.json", json.dumps(obj))
