"""Independent work revisions, immutable prose and adoption-based continuity."""
from __future__ import annotations
import json
from typing import Any, Literal

from pydantic import Field

from .models import Model
from .repository import Repository, StudioError, encode, uid


class Brief(Model):
    observer: str
    period: str
    location: str
    central_question: str
    form: str = "novel"
    voice: str = "由作者逐步校准"
    allowed_additions: list[str] = Field(default_factory=lambda: ["与世界兼容的普通人物、私人关系、局部事件"])
    protected: list[str] = Field(default_factory=lambda: ["公共制度、主要历史、地理和世界约束"])


class Artifact(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["local_entity", "plot_arc", "character_arc", "thread", "scene", "draft", "style", "example", "editorial_edit"]
    title: str = Field(min_length=1)
    text: str = ""
    refs: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class Continuity(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    category: Literal["event", "character_knowledge", "reader_knowledge", "belief", "setup", "payoff", "relationship"]
    statement: str = Field(min_length=1)
    holder: str | None = None
    refs: list[str] = Field(default_factory=list)
    evidence: str = Field(min_length=1, description="Exact excerpt from the adopted prose")
    world_time: float | None = None


class Works:
    def __init__(self, repo: Repository):
        self.repo = repo
        with repo.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY,world TEXT NOT NULL,name TEXT NOT NULL,head TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS work_revisions(id TEXT PRIMARY KEY,work TEXT NOT NULL,parent TEXT,
                    state TEXT NOT NULL,decision TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')

    def create(self, ident: str, name: str, world: str, world_revision: str, brief: dict) -> dict:
        normalized = Brief.model_validate(brief).model_dump()
        self.repo.snapshot(world, world_revision)
        if not ident.strip() or not name.strip():
            raise StudioError("work_name", "Work ID and name are required")
        with self.repo.transaction() as db:
            def action():
                if db.execute("SELECT 1 FROM works WHERE id=?", (ident,)).fetchone():
                    raise StudioError("work_exists", "Work ID already exists")
                rev = uid("wr")
                state = {"world_revision": world_revision, "brief": normalized, "artifacts": {}, "continuity": {}, "adoptions": {}}
                db.execute("INSERT INTO works VALUES(?,?,?,?)", (ident, world, name, rev))
                db.execute("INSERT INTO work_revisions(id,work,state,decision) VALUES(?,?,?,?)", (rev, ident, encode(state), "Create work"))
                return {"work": ident, "revision": rev}
            return self.repo._once(db, "work_create", ident, [name, world, world_revision, normalized], action)

    def list(self, world: str | None = None) -> list[dict]:
        with self.repo.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM works WHERE (? IS NULL OR world=?)", (world, world))]

    def get(self, work: str, revision: str | None = None, db=None) -> dict:
        if db is None:
            with self.repo.connect() as conn:
                return self.get(work, revision, conn)
        row = db.execute("SELECT * FROM works WHERE id=?", (work,)).fetchone()
        if not row:
            raise StudioError("work_missing", "Work not found")
        rev = revision or row["head"]
        item = db.execute("SELECT state FROM work_revisions WHERE work=? AND id=?", (work, rev)).fetchone()
        if not item:
            raise StudioError("work_revision", "Revision does not belong to this work")
        return {"work": work, "name": row["name"], "world": row["world"], "revision": rev, "state": json.loads(item[0])}

    def _mutate(self, work, base, key, payload, decision, mutate):
        with self.repo.transaction() as db:
            def action():
                current = self.get(work, db=db)
                if current["revision"] != base:
                    raise StudioError("stale_work", "Work changed; read its latest revision before editing")
                state = current["state"]
                world = self.repo.snapshot(current["world"], state["world_revision"], db=db)
                mutate(state, world)
                rev = uid("wr")
                db.execute("INSERT INTO work_revisions(id,work,parent,state,decision) VALUES(?,?,?,?,?)",
                           (rev, work, base, encode(state), decision))
                db.execute("UPDATE works SET head=? WHERE id=?", (rev, work))
                return {"work": work, "revision": rev, "world_revision": state["world_revision"]}
            return self.repo._once(db, "work:" + work, key, [base, payload, decision], action)

    @staticmethod
    def _refs(refs, state, world):
        missing = set(refs) - (state["artifacts"].keys() | world.keys())
        if missing:
            raise StudioError("missing_reference", "Unknown work or world references", sorted(missing))

    def save_artifact(self, work: str, base: str, artifact: dict, key: str) -> dict:
        item = Artifact.model_validate(artifact).model_dump()
        if item["kind"] in ("draft", "editorial_edit"):
            raise StudioError("scope", "Use save_prose or record_edit for immutable text assets")
        def mutate(state, world):
            old = state["artifacts"].get(item["id"])
            if old and old["kind"] != item["kind"]:
                raise StudioError("artifact_kind", "Cannot change the kind of an existing artifact")
            self._refs(item["refs"], state, world)
            if item["kind"] == "scene":
                data = item["data"]
                if not isinstance(data.get("reading_order"), (int, float)):
                    raise StudioError("scene_order", "Scene requires numeric reading_order")
                if data.get("world_time") is not None and not isinstance(data["world_time"], (int, float)):
                    raise StudioError("scene_time", "world_time must be a number on the author's time axis or null")
                self._refs([v for k, v in data.items() if k in ("pov", "location") and v], state, world)
                if any(a["id"] != item["id"] and a["kind"] == "scene" and a["data"]["reading_order"] == data["reading_order"] for a in state["artifacts"].values()):
                    raise StudioError("scene_order", "Reading order must be unique within the work")
                if old and old != item and item["id"] in state["adoptions"]:
                    self._invalidate(state, item["id"])
            state["artifacts"][item["id"]] = item
        return self._mutate(work, base, key, item, "Save work artifact", mutate)

    def save_prose(self, work: str, base: str, scene: str, text: str, key: str) -> dict:
        if not text.strip():
            raise StudioError("prose_empty", "Draft text cannot be empty")
        asset = self.repo.asset(text.encode(), ".md")
        ident = "prose_" + asset.split("/")[1].split(".")[0][:20] + "_" + scene
        def mutate(state, world):
            if state["artifacts"].get(scene, {}).get("kind") != "scene":
                raise StudioError("scene_missing", "Create a scene task before saving prose")
            state["artifacts"][ident] = {"id": ident, "kind": "draft", "title": state["artifacts"][scene]["title"],
                                         "text": "", "refs": [scene], "data": {"scene": scene, "asset": asset}}
        result = self._mutate(work, base, key, [scene, asset], "Save unadopted prose", mutate)
        return {**result, "draft": ident, "asset": asset}

    def read_prose(self, work: str, draft: str, revision: str | None = None, start: int = 0, max_chars: int = 16000) -> dict:
        if start < 0 or not 1 <= max_chars <= 60000:
            raise StudioError("pagination", "Invalid prose range")
        item = self.get(work, revision)["state"]["artifacts"].get(draft)
        if not item or item["kind"] != "draft":
            raise StudioError("draft_missing", "Draft does not belong to this work revision")
        text = self.repo.read_asset(item["data"]["asset"]).decode()
        end = min(len(text), start + max_chars)
        return {"text": text[start:end], "total_chars": len(text), "next_start": end if end < len(text) else None}

    @staticmethod
    def _invalidate(state, scene):
        target = state["artifacts"][scene]["data"]
        for record in state["continuity"].values():
            origin = state["artifacts"][record["scene"]]["data"]
            later_time = target.get("world_time") is None or origin.get("world_time") is None or origin["world_time"] >= target["world_time"]
            if record["scene"] == scene or origin["reading_order"] >= target["reading_order"] or later_time or scene in record["refs"]:
                record["status"] = "needs_review"

    def adopt(self, work: str, base: str, draft: str, continuity: list[dict], decision: str, key: str) -> dict:
        if not decision.strip():
            raise StudioError("decision_required", "Adopting prose needs an explicit author decision")
        records = [Continuity.model_validate(c).model_dump() for c in continuity]
        if len({r["id"] for r in records}) != len(records):
            raise StudioError("continuity_id", "Continuity IDs must be unique")
        def mutate(state, world):
            item = state["artifacts"].get(draft)
            if not item or item["kind"] != "draft":
                raise StudioError("draft_missing", "Draft does not belong to this work")
            prose = self.repo.read_asset(item["data"]["asset"]).decode()
            scene = item["data"]["scene"]
            # Any revision of an adopted scene invalidates dependent continuity first.
            if scene in state["adoptions"]:
                self._invalidate(state, scene)
            for c in records:
                if c["evidence"] not in prose:
                    raise StudioError("evidence", "Continuity must quote the adopted prose", c["id"])
                if c["id"] in state["continuity"] and state["continuity"][c["id"]]["scene"] != scene:
                    raise StudioError("continuity_id", "Cannot overwrite another scene's continuity")
                if c["category"] in ("character_knowledge", "belief") and not c["holder"]:
                    raise StudioError("knowledge_holder", "Character knowledge and beliefs require a holder")
                self._refs(c["refs"] + ([c["holder"]] if c["holder"] else []), state, world)
                state["continuity"][c["id"]] = {**c, "scene": scene, "draft": draft, "status": "accepted"}
            state["adoptions"][scene] = draft
        return self._mutate(work, base, key, [draft, records], decision, mutate)

    def record_edit(self, work: str, base: str, before: str, after_text: str, reason: str, tags: list[str], key: str) -> dict:
        after = self.repo.asset(after_text.encode(), ".md")
        ident = uid("edit")
        def mutate(state, world):
            original = state["artifacts"].get(before)
            if not original or original["kind"] != "draft":
                raise StudioError("draft_missing", "Original draft must belong to this work")
            state["artifacts"][ident] = {"id": ident, "kind": "editorial_edit", "title": reason,
                                         "text": reason, "refs": [], "data": {"before": original["data"]["asset"],
                                         "after": after, "tags": tags, "style_only": True}}
        return self._mutate(work, base, key, [before, after, reason, tags], "Record editorial example; no continuity change", mutate)

    def impact(self, work: str, target: str) -> dict:
        current = self.get(work)
        changes = self.repo.diff(current["world"], current["state"]["world_revision"], target)
        ids = {c["id"] for c in changes}
        state = self.repo.snapshot(current["world"], current["state"]["world_revision"])
        # Transitively include explicitly dependent world records.
        while True:
            expanded = ids | {r["id"] for r in state.values() if (set(r["refs"] + r["depends_on"]) | {r["data"].get(k) for k in ("map", "entity", "subject", "from", "to")}) & ids}
            if expanded == ids:
                break
            ids = expanded
        artifacts = current["state"]["artifacts"]
        affected = set()
        while True:
            expanded = affected | {a["id"] for a in artifacts.values() if (set(a["refs"]) | {a["data"].get("pov"), a["data"].get("location")}) & (ids | affected)}
            if expanded == affected:
                break
            affected = expanded
        return {"from": current["state"]["world_revision"], "to": target, "changes": changes,
                "affected": sorted(affected), "notice": "Explicit dependencies only; review prose for additional semantic impacts."}

    def upgrade(self, work: str, base: str, target: str, decision: str, key: str) -> dict:
        if not decision.strip():
            raise StudioError("decision_required", "World upgrade requires an explicit decision")
        current = self.get(work)
        self.repo.snapshot(current["world"], target)
        def mutate(state, world):
            state["world_revision"] = target
            for c in state["continuity"].values():
                c["status"] = "needs_review"
            # Keep manuscripts untouched; reference removals become explicit context warnings.
        return self._mutate(work, base, key, ["upgrade", target], decision, mutate)


def compile_context(works: Works, work: str, scene: str, budget_chars: int = 24000) -> dict:
    if not 2000 <= budget_chars <= 100000:
        raise StudioError("context_budget", "Use a character budget between 2000 and 100000")
    current = works.get(work)
    state = current["state"]
    artifacts = state["artifacts"]
    task = artifacts.get(scene)
    if not task or task["kind"] != "scene":
        raise StudioError("scene_missing", "Choose a scene task")
    world = works.repo.snapshot(current["world"], state["world_revision"])
    refs = set(task["refs"]) | {task["data"].get("pov"), task["data"].get("location")}
    refs.discard(None)
    missing = sorted(refs - (world.keys() | artifacts.keys()))
    for _ in range(3):
        for ident in list(refs):
            if ident in world:
                r = world[ident]
                refs.update(r["refs"] + r["depends_on"])
                refs.update(r["data"][k] for k in ("entity", "map", "from", "to") if r["data"].get(k))
    world_items = [r for r in world.values() if r["status"] == "accepted" and (r["id"] in refs or r["kind"] == "constraint" or r["data"].get("map") in refs)]
    knowledge = []
    for c in state["continuity"].values():
        if c["status"] != "accepted" or c["scene"] == scene:
            continue
        origin = artifacts[c["scene"]]["data"]
        if c["category"] == "reader_knowledge":
            eligible = origin["reading_order"] < task["data"]["reading_order"]
        else:
            when = c["world_time"] if c["world_time"] is not None else origin.get("world_time")
            eligible = when is not None and task["data"].get("world_time") is not None and when <= task["data"]["world_time"]
            if c["category"] in ("character_knowledge", "belief"):
                eligible = eligible and c["holder"] == task["data"].get("pov")
        if eligible:
            knowledge.append(c)
    result = {"work": work, "work_revision": current["revision"], "world_revision": state["world_revision"],
              "brief": state["brief"], "scene_plan_not_fact": task, "world": [], "continuity": [],
              "work_material": [], "style_examples_only": [], "missing": missing, "omitted": [],
              "notice": "World truth, beliefs, reader knowledge, plans and style examples are distinct. Only accepted continuity is included."}
    if len(encode(result)) > budget_chars:
        raise StudioError("context_budget", "Brief and scene alone exceed the budget; increase it or shorten the plan")
    materials = [a for a in artifacts.values() if a["kind"] in ("plot_arc", "character_arc", "thread", "style") or (a["id"] in refs and a["kind"] == "local_entity")]
    examples = []
    for a in artifacts.values():
        if a["kind"] not in ("example", "editorial_edit"):
            continue
        example = dict(a)
        if a["kind"] == "editorial_edit":
            example = {**a, "before_text": works.repo.read_asset(a["data"]["before"]).decode(),
                       "after_text": works.repo.read_asset(a["data"]["after"]).decode()}
        examples.append(example)
    examples.sort(key=lambda a: -len(set(a["data"].get("tags", [])) & set(task["data"].get("style_tags", []))))
    for section, items in (("world", world_items), ("continuity", knowledge), ("work_material", materials), ("style_examples_only", examples[:5])):
        for item in items:
            result[section].append(item)
            if len(encode(result)) > budget_chars - 300:
                result[section].pop()
                result["omitted"].append({"section": section, "id": item["id"]})
    result["needs_review"] = [c["id"] for c in state["continuity"].values() if c["status"] == "needs_review"]
    result["truncated"] = bool(result["omitted"])
    result["omitted_count"] = len(result["omitted"])
    result["review_count"] = len(result["needs_review"])
    while len(encode(result)) > budget_chars - 100 and (result["omitted"] or result["needs_review"]):
        (result["omitted"] if result["omitted"] else result["needs_review"]).pop()
    result["characters"] = len(encode(result))
    return result
