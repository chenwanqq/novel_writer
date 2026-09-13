"""Inspectable exports and self-contained backups with verified asset integrity."""
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .repository import Repository, StudioError, encode, uid


def backup(repo: Repository) -> dict:
    exports = repo.root / "exports"
    exports.mkdir(exist_ok=True)
    target = exports / f"{uid('backup')}.zip"
    with tempfile.TemporaryDirectory(prefix="world-backup-") as directory:
        copy = Path(directory) / "world.sqlite"
        with repo.connect() as source, sqlite3.connect(copy) as dest:
            source.backup(dest)
        # Assets are immutable and never automatically removed. Copying extra unreferenced assets is safe.
        entries = [("world.sqlite", copy)] + [(p.relative_to(repo.root).as_posix(), p) for p in sorted((repo.root / "assets").iterdir()) if p.is_file() and not p.is_symlink() and not p.name.startswith("pending_")]
        checksums = {}
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in entries:
                data = path.read_bytes()
                checksums[name] = hashlib.sha256(data).hexdigest()
                archive.writestr(name, data)
            archive.writestr("manifest.json", encode({"format": 1, "sha256": checksums}))
    return {"path": str(target), "files": len(entries), "note": "Contains all worlds, works, sources and immutable assets; excludes runtime credentials."}


def restore(archive_path: str, target_path: str) -> dict:
    target = Path(target_path).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise StudioError("restore_target", "Restore requires an empty destination; existing data is never overwritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="world-restore-", dir=target.parent) as directory:
        staging = Path(directory)
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > 100000 or sum(i.file_size for i in infos) > 2_000_000_000:
                raise StudioError("backup_invalid", "Duplicate entries or oversized archive")
            if "manifest.json" not in names or "world.sqlite" not in names:
                raise StudioError("backup_invalid", "Backup manifest or database is missing")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != 1 or set(names) != set(manifest.get("sha256", {})) | {"manifest.json"}:
                raise StudioError("backup_invalid", "Unrecognized manifest")
            for name, expected in manifest["sha256"].items():
                path = (staging / name).resolve()
                if not path.is_relative_to(staging) or (name != "world.sqlite" and not name.startswith("assets/")):
                    raise StudioError("backup_path", "Invalid archive member path")
                content = archive.read(name)
                actual = hashlib.sha256(content).hexdigest()
                if actual != expected:
                    raise StudioError("backup_checksum", "Backup checksum mismatch", name)
                if name.startswith("assets/") and Path(name).stem != actual:
                    raise StudioError("asset_checksum", "Asset does not match its content address", name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            with sqlite3.connect(staging / "world.sqlite") as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StudioError("backup_database", "Database integrity check failed")
                if db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] != "1":
                    raise StudioError("schema_version", "Unsupported backup schema")
        target.mkdir(exist_ok=True)
        for child in staging.iterdir():
            shutil.move(str(child), str(target / child.name))
    return {"data": str(target), "status": "restored"}


def export_markdown(repo: Repository, world: str, revision: str | None = None) -> dict:
    revision = revision or repo.head(world)
    state = repo.snapshot(world, revision)
    lines = [f"# {world}", "", f"世界版本：{revision}", "", "此文件为只读导出视图；正式修改通过变更集提交。", ""]
    for record in state.values():
        lines.extend([f"## {record['name']}", "", f"ID: {record['id']} · {record['kind']} · {record['status']}", "", record["text"], ""])
        if record["data"]:
            lines.extend(["```json", json.dumps(record["data"], ensure_ascii=False, indent=2), "```", ""])
        for source in record["sources"]:
            lines.append(f"来源：{source['source_id']} / {source['locator']}")
    target = repo.root / "exports" / f"{world}-{revision}.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return {"path": str(target), "revision": revision, "records": len(state)}


def export_work(repo: Repository, work: str, revision: str | None = None) -> dict:
    """Export only adopted prose at one immutable work revision, in reading order."""
    from .works import Works
    current = Works(repo).get(work, revision)
    state = current["state"]
    scenes = sorted((state["artifacts"][ident] for ident in state["adoptions"]),
                    key=lambda item: item["data"]["reading_order"])
    lines = [f"# {current['name']}", "", f"作品版本：{current['revision']}",
             f"世界版本：{state['world_revision']}", "", "此文件只包含已采纳正文，是只读导出视图。", ""]
    for scene in scenes:
        draft = state["artifacts"][state["adoptions"][scene["id"]]]
        lines.extend([f"## {scene['title']}", "", repo.read_asset(draft["data"]["asset"]).decode(), ""])
    target = repo.root / "exports" / f"work-{work}-{current['revision']}.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return {"path": str(target), "revision": current["revision"],
            "world_revision": state["world_revision"], "scenes": len(scenes)}
