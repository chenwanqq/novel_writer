import pytest
from world_studio.repository import Repository, StudioError


def put(ident="council", **extra):
    return {"action": "put", "id": ident, "record": {"id": ident, "kind": "entity", "name": "议会", "status": "accepted", **extra}}


def test_versions_branches_restore_and_stale(tmp_path):
    r = Repository(tmp_path)
    base = r.create_world("w", "世界")["revision"]
    r.branch("w", "alternate", base)
    p = r.propose("w", "main", base, [put()], "a")
    stale = r.propose("w", "main", base, [put("other")], "b")
    result = r.commit(p["change_set"], "作者采用议会设定")
    assert r.commit(p["change_set"], "重试") == result
    assert not r.snapshot("w", base)
    assert not r.snapshot("w", branch="alternate")
    with pytest.raises(StudioError, match="World changed"):
        r.commit(stale["change_set"], "采用")
    assert "other" not in r.snapshot("w")
    restore = r.restore("w", "main", result["revision"], base, "restore")
    restored = r.commit(restore["change_set"], "恢复")
    assert restored["revision"] != base
    assert not r.snapshot("w")
    assert r.snapshot("w", result["revision"])["council"]


def test_conflicts_references_and_idempotency(tmp_path):
    r = Repository(tmp_path)
    base = r.create_world("w", "世界")["revision"]
    a = put("seats", kind="fact", data={"subject": "council", "attribute": "seats", "value": 12})
    b = put("alternative", kind="fact", data={"subject": "council", "attribute": "seats", "value": 24})
    p = r.propose("w", "main", base, [put(), a, b], "conflict")
    assert r.preview(p["change_set"])["issues"][0]["code"] == "attribute_conflict"
    with pytest.raises(StudioError):
        r.commit(p["change_set"], "采用")
    assert r.head("w") == base
    with pytest.raises(StudioError, match="different request"):
        r.propose("w", "main", base, [put()], "conflict")
    b["record"]["status"] = "candidate"
    p = r.propose("w", "main", base, [put(), a, b], "resolved")
    r.commit(p["change_set"], "采用十二席，二十四席待定")
    p = r.propose("w", "main", r.head("w"), [{"action": "delete", "id": "council"}], "delete")
    assert r.preview(p["change_set"])["issues"]


def test_disjoint_fact_intervals_and_parallel_writers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    r = Repository(tmp_path)
    base = r.create_world("w", "世界")["revision"]
    a = put("early", kind="fact", valid_from=1, valid_to=10,
            data={"subject": "council", "attribute": "seats", "value": 12})
    b = put("late", kind="fact", valid_from=10,
            data={"subject": "council", "attribute": "seats", "value": 24})
    first = r.propose("w", "main", base, [put(), a, b], "time")
    second = r.propose("w", "main", base, [put("other")], "parallel")

    def commit(proposal):
        try:
            return Repository(tmp_path).commit(proposal["change_set"], "采用")["revision"]
        except StudioError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, [first, second]))
    assert results.count("stale_base") == 1
    assert len(r.snapshot("w")) in (1, 3)
