"""SQLite transactions and immutable snapshots shared by every adapter."""
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import contained, data_path
from .models import Change, Record


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class StudioError(ValueError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.details = code, details


class Repository:
    def __init__(self, root: str | Path | None = None):
        self.root = data_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "assets").mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT OR IGNORE INTO meta VALUES('schema','1');
                CREATE TABLE IF NOT EXISTS worlds(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(
                    id TEXT PRIMARY KEY,world TEXT NOT NULL REFERENCES worlds(id),parent TEXT,
                    snapshot TEXT NOT NULL,decision TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS branches(world TEXT NOT NULL,name TEXT NOT NULL,
                    head TEXT NOT NULL REFERENCES revisions(id),PRIMARY KEY(world,name));
                CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,world TEXT NOT NULL,
                    branch TEXT NOT NULL,base TEXT NOT NULL,changes TEXT NOT NULL,
                    decision TEXT NOT NULL DEFAULT '',result TEXT);
                CREATE TABLE IF NOT EXISTS operations(scope TEXT,key TEXT,fingerprint TEXT,result TEXT,
                    PRIMARY KEY(scope,key));
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,world TEXT NOT NULL,
                    hash TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,asset TEXT NOT NULL,
                    units TEXT NOT NULL,UNIQUE(world,hash,role));
                CREATE TABLE IF NOT EXISTS progress(source TEXT,unit TEXT,result TEXT NOT NULL,
                    PRIMARY KEY(source,unit));
            ''')
            if db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] != "1":
                raise StudioError("schema_version", "Unsupported database version; use a compatible release")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.root / "world.sqlite", timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def asset(self, content: bytes, suffix: str = ".bin") -> str:
        if not re.fullmatch(r"\.[a-z0-9]+", suffix):
            raise StudioError("asset_type", "Invalid asset extension")
        name = f"assets/{hashlib.sha256(content).hexdigest()}{suffix}"
        path = contained(self.root, name)
        if not path.exists():
            # Each completed object is published atomically; failed objects have no database reference.
            temp = self.root / "assets" / uid("pending")
            temp.write_bytes(content)
            temp.replace(path)
        return name

    def read_asset(self, name: str) -> bytes:
        if not re.fullmatch(r"assets/[a-f0-9]{64}\.[a-z0-9]+", name):
            raise StudioError("asset_path", "Expected a content-addressed asset path")
        return contained(self.root, name).read_bytes()

    def _once(self, db, scope, key, payload, action):
        if not key.strip():
            raise StudioError("idempotency", "A non-empty idempotency key is required")
        fingerprint = hashlib.sha256(encode(payload).encode()).hexdigest()
        row = db.execute("SELECT * FROM operations WHERE scope=? AND key=?", (scope, key)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise StudioError("idempotency_conflict", "Key was already used for a different request")
            return json.loads(row["result"])
        result = action()
        db.execute("INSERT INTO operations VALUES(?,?,?,?)", (scope, key, fingerprint, encode(result)))
        return result

    def create_world(self, world: str, name: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", world) or not name.strip():
            raise StudioError("world_id", "Provide a name and an ASCII world identifier")
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM worlds WHERE id=?", (world,)).fetchone()
            if existing:
                if existing["name"] != name:
                    raise StudioError("world_exists", "World ID already has a different name")
                return {"world": world, "revision": self.head(world, db=db)}
            rev = uid("r")
            db.execute("INSERT INTO worlds VALUES(?,?)", (world, name))
            db.execute("INSERT INTO revisions(id,world,snapshot,decision) VALUES(?,?,?,?)",
                       (rev, world, "{}", "Create world"))
            db.execute("INSERT INTO branches VALUES(?,?,?)", (world, "main", rev))
            return {"world": world, "revision": rev}

    def list_worlds(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT w.id,w.name,b.name branch,b.head FROM worlds w JOIN branches b ON w.id=b.world")]

    def head(self, world: str, branch: str = "main", db=None) -> str:
        if db is None:
            with self.connect() as conn:
                return self.head(world, branch, conn)
        row = db.execute("SELECT head FROM branches WHERE world=? AND name=?", (world, branch)).fetchone()
        if not row:
            raise StudioError("branch_missing", "World or branch does not exist")
        return row[0]

    def snapshot(self, world: str, revision: str | None = None, branch: str = "main", db=None) -> dict:
        if db is None:
            with self.connect() as conn:
                return self.snapshot(world, revision, branch, conn)
        revision = revision or self.head(world, branch, db)
        row = db.execute("SELECT snapshot FROM revisions WHERE world=? AND id=?", (world, revision)).fetchone()
        if not row:
            raise StudioError("revision_missing", "Revision does not belong to this world")
        return json.loads(row[0])

    def branch(self, world: str, name: str, revision: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name):
            raise StudioError("branch_name", "Invalid branch name")
        with self.transaction() as db:
            self.snapshot(world, revision, db=db)
            existing = db.execute("SELECT head FROM branches WHERE world=? AND name=?", (world, name)).fetchone()
            if existing and existing[0] != revision:
                raise StudioError("branch_exists", "Branch exists at another revision")
            db.execute("INSERT OR IGNORE INTO branches VALUES(?,?,?)", (world, name, revision))
        return {"branch": name, "revision": revision}

    def propose(self, world: str, branch: str, base: str, changes: list[dict], key: str) -> dict:
        normalized = [Change.model_validate(c).model_dump(mode="json") for c in changes]
        if len({c["id"] for c in normalized}) != len(normalized):
            raise StudioError("duplicate_change", "Each record can be changed only once per proposal")
        with self.transaction() as db:
            self.snapshot(world, base, db=db)
            self.head(world, branch, db)
            def save():
                ident = uid("change")
                db.execute("INSERT INTO proposals(id,world,branch,base,changes) VALUES(?,?,?,?,?)",
                           (ident, world, branch, base, encode(normalized)))
                return {"change_set": ident, "base": base}
            return self._once(db, "propose:" + world, key, [branch, base, normalized], save)

    def _preview(self, db, proposal: str):
        row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal,)).fetchone()
        if not row:
            raise StudioError("proposal_missing", "Change set not found")
        state = self.snapshot(row["world"], row["base"], db=db)
        for change in json.loads(row["changes"]):
            if change["action"] == "delete":
                if change["id"] not in state:
                    raise StudioError("record_missing", f"Cannot delete {change['id']}")
                del state[change["id"]]
            else:
                state[change["id"]] = change["record"]
        return row, state

    def validate(self, state: dict, world: str, db) -> list[dict]:
        issues = []
        for ident, raw in state.items():
            record = Record.model_validate(raw)
            refs = record.refs + record.depends_on + record.supersedes
            refs += [v for k, v in record.data.items() if k in ("subject", "entity", "map", "from", "to", "child_map") and v]
            for ref in refs:
                if ref not in state:
                    issues.append({"record": ident, "code": "missing_reference", "reference": ref})
            for source in record.sources:
                row = db.execute("SELECT units FROM sources WHERE id=? AND world=?", (source.source_id, world)).fetchone()
                if not row or source.locator not in {u["id"] for u in json.loads(row[0])}:
                    issues.append({"record": ident, "code": "missing_source_locator"})
        facts = [r for r in state.values() if r["status"] == "accepted" and r["kind"] == "fact" and "attribute" in r["data"]]
        for i, a in enumerate(facts):
            for b in facts[i + 1:]:
                if (a["data"].get("subject"), a["data"]["attribute"]) != (b["data"].get("subject"), b["data"]["attribute"]):
                    continue
                af, at = a["valid_from"], a["valid_to"]
                bf, bt = b["valid_from"], b["valid_to"]
                overlaps = max(af if af is not None else -float("inf"), bf if bf is not None else -float("inf")) < min(at if at is not None else float("inf"), bt if bt is not None else float("inf"))
                if overlaps and a["data"].get("value") != b["data"].get("value"):
                    issues.append({"record": a["id"], "other": b["id"], "code": "attribute_conflict"})
        return issues

    def preview(self, proposal: str) -> dict:
        with self.connect() as db:
            row, state = self._preview(db, proposal)
            return {"change_set": proposal, "base": row["base"], "head": self.head(row["world"], row["branch"], db),
                    "changes": json.loads(row["changes"]), "issues": self.validate(state, row["world"], db)}

    def commit(self, proposal: str, decision: str) -> dict:
        if not decision.strip():
            raise StudioError("decision_required", "Record the author's explicit adoption decision")
        with self.transaction() as db:
            row, state = self._preview(db, proposal)
            if row["result"]:
                return json.loads(row["result"])
            if self.head(row["world"], row["branch"], db) != row["base"]:
                raise StudioError("stale_base", "World changed; compare revisions and create a new proposal", self.preview(proposal))
            issues = self.validate(state, row["world"], db)
            if issues:
                raise StudioError("validation", "Resolve change-set issues before committing", issues)
            rev = uid("r")
            db.execute("INSERT INTO revisions(id,world,parent,snapshot,decision) VALUES(?,?,?,?,?)",
                       (rev, row["world"], row["base"], encode(state), decision))
            db.execute("UPDATE branches SET head=? WHERE world=? AND name=?", (rev, row["world"], row["branch"]))
            result = {"revision": rev, "world": row["world"], "branch": row["branch"], "change_set": proposal}
            db.execute("UPDATE proposals SET decision=?,result=? WHERE id=?", (decision, encode(result), proposal))
            return result

    def diff(self, world: str, before: str, after: str) -> list[dict]:
        a, b = self.snapshot(world, before), self.snapshot(world, after)
        return [{"id": k, "before": a.get(k), "after": b.get(k)} for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]

    def restore(self, world: str, branch: str, base: str, target: str, key: str) -> dict:
        current, old = self.snapshot(world, base), self.snapshot(world, target)
        changes = [{"action": "put", "id": k, "record": v} for k, v in old.items()]
        changes += [{"action": "delete", "id": k} for k in current.keys() - old.keys()]
        return self.propose(world, branch, base, changes, key)
