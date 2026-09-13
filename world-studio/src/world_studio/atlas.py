"""Versioned spatial objects and durable, optimistic editor drafts."""
import base64
import heapq
import io
import json
from typing import Literal

from PIL import Image
from pydantic import Field, model_validator

from .models import Model, Record
from .repository import Repository, StudioError, encode, uid


class MapData(Model):
    width: float = Field(default=1600, gt=0, le=100000)
    height: float = Field(default=1000, gt=0, le=100000)
    asset: str | None = None
    units_per_km: float | None = Field(default=None, gt=0)


class PlaceData(Model):
    map: str
    entity: str
    x: float
    y: float
    child_map: str | None = None


class RouteData(Model):
    map: str
    start: str = Field(alias="from")
    end: str = Field(alias="to")
    mode: str = "步行"
    bidirectional: bool = True
    min_days: float | None = Field(default=None, ge=0)
    max_days: float | None = Field(default=None, ge=0)
    availability: Literal["open", "closed", "unknown"] = "open"
    conditions: list[str] = Field(default_factory=list)
    points: list[tuple[float, float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def duration(self):
        if (self.min_days is None) != (self.max_days is None):
            raise ValueError("Provide both minimum and maximum travel time or neither")
        if self.min_days is not None and self.max_days < self.min_days:
            raise ValueError("Maximum travel time must not be less than minimum")
        if self.start == self.end:
            raise ValueError("A route must connect two different places")
        return self


class RegionData(Model):
    map: str
    points: list[tuple[float, float]] = Field(min_length=3)
    color: str = Field(default="#bdd8ca", pattern=r"^#[a-fA-F0-9]{6}$")
    entity: str | None = None


def validate_atlas(state: dict, repo: Repository) -> list[dict]:
    issues = []
    for ident, record in state.items():
        kind, data = record["kind"], record["data"]
        if kind not in ("map", "place", "route", "region"):
            continue
        try:
            model = {"map": MapData, "place": PlaceData, "route": RouteData, "region": RegionData}[kind]
            obj = model.model_validate(data)
            if kind == "map":
                if obj.asset:
                    with Image.open(io.BytesIO(repo.read_asset(obj.asset))) as image:
                        if image.format not in ("PNG", "JPEG", "WEBP"):
                            raise ValueError("Unsupported background image")
                continue
            if state.get(obj.map, {}).get("kind") != "map":
                raise ValueError("map must reference a map record")
            if kind in ("place", "region") and obj.entity:
                if state.get(obj.entity, {}).get("kind") != "entity":
                    raise ValueError("entity must reference an entity record")
            if kind == "place" and obj.child_map:
                if state.get(obj.child_map, {}).get("kind") != "map":
                    raise ValueError("child_map must reference a map")
            if kind == "route":
                for place in (obj.start, obj.end):
                    if state.get(place, {}).get("kind") != "place" or state[place]["data"].get("map") != obj.map:
                        raise ValueError("Route endpoints must be places on the same map")
        except (ValueError, OSError) as exc:
            issues.append({"record": ident, "code": "atlas_invalid", "message": str(exc)})
    return issues


class Atlas:
    def __init__(self, repo: Repository):
        self.repo = repo
        with repo.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS map_drafts(
                id TEXT PRIMARY KEY,world TEXT,branch TEXT,base TEXT,state TEXT,version INTEGER,
                committed TEXT)""")

    def upload(self, content_base64: str) -> dict:
        try:
            data = base64.b64decode(content_base64, validate=True)
            if len(data) > 20 * 1024 * 1024:
                raise ValueError("Maximum background size is 20 MB")
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ("PNG", "JPEG", "WEBP") or image.width * image.height > 40_000_000:
                    raise ValueError("Use PNG/JPEG/WebP up to 40 megapixels")
                suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[image.format]
                width, height = image.size
                image.verify()
        except (ValueError, OSError, Image.DecompressionBombError) as exc:
            raise StudioError("image_invalid", str(exc)) from exc
        return {"asset": self.repo.asset(data, suffix), "width": width, "height": height}

    def background(self, asset: str) -> dict:
        raw = self.repo.read_asset(asset)
        with Image.open(io.BytesIO(raw)) as image:
            mime = Image.MIME[image.format]
        return {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}

    def new_draft(self, world: str, branch: str = "main", revision: str | None = None) -> dict:
        with self.repo.transaction() as db:
            base = revision or self.repo.head(world, branch, db)
            state = self.repo.snapshot(world, base, db=db)
            ident = uid("draft")
            db.execute("INSERT INTO map_drafts VALUES(?,?,?,?,?,0,NULL)", (ident, world, branch, base, encode(state)))
        return self.draft(ident)

    def draft(self, ident: str) -> dict:
        with self.repo.connect() as db:
            row = db.execute("SELECT * FROM map_drafts WHERE id=?", (ident,)).fetchone()
            if not row:
                raise StudioError("draft_missing", "Map draft not found")
            value = dict(row)
            value["state"] = json.loads(value["state"])
            value["head"] = self.repo.head(value["world"], value["branch"], db)
            return value

    def save(self, ident: str, version: int, state: dict) -> dict:
        normalized = {k: Record.model_validate(v).model_dump(mode="json") for k, v in state.items()}
        if any(k != v["id"] for k, v in normalized.items()):
            raise StudioError("record_id", "Record key and ID must match")
        with self.repo.transaction() as db:
            row = db.execute("SELECT * FROM map_drafts WHERE id=?", (ident,)).fetchone()
            if not row:
                raise StudioError("draft_missing", "Draft not found")
            if row["version"] != version or row["committed"]:
                raise StudioError("stale_draft", "Draft changed or was committed; reload without discarding your edits")
            # Editors may change spatial records or associated entities, not arbitrary world facts.
            before = self.repo.snapshot(row["world"], row["base"], db=db)
            for k in before.keys() | normalized.keys():
                if before.get(k) != normalized.get(k):
                    if any(r and r["kind"] not in ("map", "place", "route", "region", "entity") for r in (before.get(k), normalized.get(k))):
                        raise StudioError("scope", "Map drafts may only modify spatial records and entities")
            issues = self.repo.validate(normalized, row["world"], db)
            if issues:
                raise StudioError("validation", "Resolve map draft issues", issues)
            db.execute("UPDATE map_drafts SET state=?,version=version+1 WHERE id=?", (encode(normalized), ident))
        return self.draft(ident)

    def proposal(self, ident: str, version: int) -> dict:
        draft = self.draft(ident)
        if draft["version"] != version:
            raise StudioError("stale_draft", "Reload the draft before proposing changes")
        before = self.repo.snapshot(draft["world"], draft["base"])
        changes = []
        for k in sorted(before.keys() | draft["state"].keys()):
            if before.get(k) == draft["state"].get(k):
                continue
            changes.append({"action": "put", "id": k, "record": draft["state"][k]} if k in draft["state"] else {"action": "delete", "id": k})
        return self.repo.propose(draft["world"], draft["branch"], draft["base"], changes, f"map:{ident}:{version}")

    def commit(self, ident: str, version: int, decision: str) -> dict:
        # Freeze the draft against concurrent saves while the shared commit transaction runs.
        with self.repo.transaction() as db:
            row = db.execute("SELECT version,committed FROM map_drafts WHERE id=?", (ident,)).fetchone()
            if not row or row[0] != version:
                raise StudioError("stale_draft", "Draft changed; inspect it before committing")
            if row[1] and row[1] != "pending":
                return json.loads(row[1])
            db.execute("UPDATE map_drafts SET committed='pending' WHERE id=?", (ident,))
        try:
            proposal = self.proposal(ident, version)
            result = self.repo.commit(proposal["change_set"], decision)
        except BaseException:
            with self.repo.transaction() as db:
                db.execute("UPDATE map_drafts SET committed=NULL WHERE id=? AND committed='pending'", (ident,))
            raise
        with self.repo.transaction() as db:
            db.execute("UPDATE map_drafts SET committed=? WHERE id=?", (encode(result), ident))
        return result

    def rebase(self, ident: str, version: int) -> dict:
        """Three-way reapply disjoint edits; conflicts keep the original draft untouched."""
        with self.repo.transaction() as db:
            row = db.execute("SELECT * FROM map_drafts WHERE id=?", (ident,)).fetchone()
            if not row or row["version"] != version or row["committed"]:
                raise StudioError("stale_draft", "Reload draft before reapplying")
            base = self.repo.snapshot(row["world"], row["base"], db=db)
            head = self.repo.head(row["world"], row["branch"], db)
            current = self.repo.snapshot(row["world"], head, db=db)
            local = json.loads(row["state"])
            conflicts = []
            for k in base.keys() | local.keys():
                if base.get(k) == local.get(k):
                    continue
                if current.get(k) != base.get(k) and current.get(k) != local.get(k):
                    conflicts.append({"id": k, "base": base.get(k), "local": local.get(k), "remote": current.get(k)})
                elif k in local:
                    current[k] = local[k]
                else:
                    current.pop(k, None)
            if conflicts:
                raise StudioError("merge_conflict", "Resolve conflicting objects explicitly; draft retained", conflicts)
            issues = self.repo.validate(current, row["world"], db)
            if issues:
                raise StudioError("validation", "Reapplied draft is invalid", issues)
            db.execute("UPDATE map_drafts SET base=?,state=?,version=version+1 WHERE id=?", (head, encode(current), ident))
        return self.draft(ident)


def route_query(repo: Repository, world: str, start: str, end: str, revision: str | None = None,
                conditions: list[str] | None = None, mode: str | None = None, available_days: float | None = None) -> dict:
    state = repo.snapshot(world, revision)
    if any(state.get(p, {}).get("kind") != "place" for p in (start, end)):
        raise StudioError("place_missing", "Select existing start and destination places")
    known = set(conditions or [])
    graph, possible, unknown = {}, {}, set()
    for record in state.values():
        if record["kind"] != "route" or record["status"] != "accepted":
            continue
        route = RouteData.model_validate(record["data"])
        if route.availability == "closed" or (mode and route.mode != mode):
            continue
        uncertain = route.availability == "unknown" or bool(set(route.conditions) - known) or route.min_days is None
        if uncertain:
            unknown.add(record["id"])
        pairs = [(route.start, route.end)] + ([(route.end, route.start)] if route.bidirectional else [])
        for a, b in pairs:
            possible.setdefault(a, []).append(b)
            if not uncertain:
                graph.setdefault(a, []).append((b, route.min_days, route.max_days, record["id"]))
    queue = [(0.0, 0.0, start, [])]
    best = {}
    while queue:
        minimum, maximum, place, path = heapq.heappop(queue)
        if place in best:
            continue
        best[place] = minimum
        if place == end:
            timing = None if available_days is None else ("impossible" if available_days < minimum else "possible" if available_days >= maximum else "uncertain")
            return {"status": "reachable", "routes": path, "min_days": minimum, "max_days": maximum,
                    "timing": timing, "basis": "fastest known minimum-time route; maximum is for this same path",
                    "unverified_routes": sorted(unknown)}
        for dest, low, high, ident in graph.get(place, []):
            if dest not in best:
                heapq.heappush(queue, (minimum + low, maximum + high, dest, path + [ident]))
    seen, stack = set(), [start]
    while stack:
        place = stack.pop()
        if place not in seen:
            seen.add(place)
            stack.extend(possible.get(place, []))
    return {"status": "insufficient_information" if end in seen else "unreachable", "routes": [],
            "unverified_routes": sorted(unknown)}
