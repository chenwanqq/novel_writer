"""Synthetic end-to-end fixture; never runs implicitly on a user's repository."""
from .atlas import Atlas, route_query
from .ingestion import Ingestion
from .repository import Repository, StudioError
from .works import Works, compile_context


def seed_demo(repo: Repository) -> dict:
    if repo.list_worlds():
        raise StudioError("demo_not_empty", "Use a separate empty --data directory for the demo")
    base = repo.create_world("northern", "北境诸国")["revision"]
    ingestion = Ingestion(repo)
    source = ingestion.ingest("northern", "议会讨论.md", "议会设十二席。\n假设扩大到二十四席？\n仍采用十二席，地方代表性通过另一院解决。", "chat")
    changes = []
    def add(ident, kind, name, data=None, text="", status="accepted", **extra):
        changes.append({"action": "put", "id": ident, "record": {"id": ident, "kind": kind, "name": name, "data": data or {}, "text": text, "status": status, **extra}})
    add("council", "entity", "议会")
    add("seats", "fact", "议会十二席", {"subject": "council", "attribute": "seats", "value": 12},
        sources=[{"source_id": source["source_id"], "locator": "document", "excerpt": "仍采用十二席"}])
    add("seats_candidate", "hypothesis", "二十四席方案", text="讨论过，但没有采用。", status="rejected")
    add("continent", "map", "大陆", {"width": 1600, "height": 1000})
    add("port_city", "map", "东港城", {"width": 1000, "height": 800})
    add("north_region", "region", "北境诸国", {"map": "continent", "color": "#bdd8ca", "points": [[260,590],[340,300],[580,210],[710,100],[900,160],[1060,310],[1300,490],[1210,680],[970,780],[850,870],[710,800],[470,870],[330,740]]})
    for ident, name, x, y in [("capital", "首都", 480, 680), ("gate", "北关", 780, 330), ("port", "东港", 1220, 600)]:
        add(ident + "_entity", "entity", name)
        data = {"map": "continent", "entity": ident + "_entity", "x": x, "y": y}
        if ident == "port":
            data["child_map"] = "port_city"
        add(ident, "place", name, data, text="北境东部的重要港口，连接海外与内陆的贸易。" if ident == "port" else "")
    add("road_north", "route", "北境驿道", {"map": "continent", "from": "capital", "to": "gate", "min_days": 3, "max_days": 5, "points": [[600,460]], "mode": "信使", "bidirectional": True, "availability": "open", "conditions": []})
    add("road_port", "route", "东港商道", {"map": "continent", "from": "gate", "to": "port", "min_days": 2, "max_days": 4, "points": [[980,420]], "mode": "信使", "bidirectional": True, "availability": "open", "conditions": []})
    add("clerk", "entity", "沈衡", text="地方银行年轻记账员。")
    add("bank_entity", "entity", "东港银行")
    add("bank", "place", "银行", {"map": "port_city", "entity": "bank_entity", "x": 500, "y": 400})
    proposal = repo.propose("northern", "main", base, changes, "demo-world")
    revision = repo.commit(proposal["change_set"], "作者采用十二席与示范地图；二十四席保留为否决方案")["revision"]
    ingestion.reviewed(source["source_id"], "document", "已读取全文并保留否决方案", [proposal["change_set"]])
    repo.branch("northern", "federal", revision)
    works = Works(repo)
    brief = {"observer": "沈衡，地方银行记账员", "period": "银行改革第一年", "location": "东港", "central_question": "为了保住家人，他会隐瞒多少？", "voice": "克制，贴近人物，让动作承担部分解释"}
    works.create("ledger", "东港账簿", "northern", revision, brief)
    works.create("sister", "码头来信", "northern", revision, {**brief, "observer": "记账员姐姐"})
    works.save_artifact("ledger", works.get("ledger")["revision"], {"id": "arc", "kind": "character_arc", "title": "第一次妥协", "text": "相信程序 → 发现矛盾 → 决定暂缓披露 → 欠下人情。"}, "arc")
    for ident, title, order in [("scene1", "钥匙", 1), ("scene2", "第二天的账目", 2)]:
        works.save_artifact("ledger", works.get("ledger")["revision"], {"id": ident, "kind": "scene", "title": title,
            "refs": ["bank", "clerk", "arc"], "data": {"reading_order": order, "world_time": order, "pov": "clerk", "location": "bank", "goal": "拿到真实账册", "pressure": "公开可能使救济拨款冻结", "style_tags": ["间接拒绝"]}}, ident)
    draft = works.save_prose("ledger", works.get("ledger")["revision"], "scene1", "“库房的钥匙呢？”沈衡问。\n陈大人摸了摸袖口。\n沈衡把手伸了出来。", "draft")
    works.adopt("ledger", draft["revision"], draft["draft"], [{"id": "asked_key", "category": "event", "statement": "沈衡索取钥匙", "evidence": "库房的钥匙呢", "refs": ["clerk"]}], "采用示范正文", "adopt")
    works.record_edit("ledger", works.get("ledger")["revision"], draft["draft"], "沈衡把手伸了出来。\n“交给小赵。”", "让动作和权限转移承担解释", ["间接拒绝"], "edit")
    Atlas(repo)
    return {"world": "northern", "revision": revision, "works": ["ledger", "sister"],
            "route": route_query(repo, "northern", "capital", "port"),
            "context": compile_context(works, "ledger", "scene2"), "source": source}
