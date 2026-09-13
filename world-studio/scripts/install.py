#!/usr/bin/env python3
"""Install a local MCP + skills connection without changing unrelated Codex settings.

The plugin bundle remains available for marketplace installation. This direct local
route is useful for development and hosts whose plugin loader lacks stdio support.
"""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", default=shutil.which("codex") or "codex", help="Path to a working Codex CLI")
    parser.add_argument("--data", required=True, help="Absolute persistent data directory outside the plugin")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without performing them")
    args = parser.parse_args()
    plugin = Path(__file__).resolve().parents[1]
    data = Path(args.data).expanduser().resolve()
    if data.is_relative_to(plugin):
        parser.error("Data must be outside the plugin directory")
    uv = shutil.which("uv")
    if not uv:
        parser.error("Install uv first")
    skills_root = Path.home() / ".agents" / "skills"
    command = [args.codex, "mcp", "add", "world-studio", "--env", f"WORLD_STUDIO_DATA={data}",
               "--", uv, "run", "--directory", str(plugin), "--frozen", "world-studio", "mcp"]
    actions = {"mcp_command": command, "skills": [str(skills_root / n) for n in ("world-input", "world-write")],
               "data": str(data), "notice": "Direct local MCP + skills connection; does not install a marketplace entry."}
    if args.dry_run:
        print(json.dumps(actions, ensure_ascii=False, indent=2))
        return
    # Inspect before replacing any global connection or skill.
    listed = subprocess.run([args.codex, "mcp", "list", "--json"], capture_output=True, text=True, check=True)
    existing = json.loads(listed.stdout)
    if any(item.get("name") == "world-studio" for item in existing):
        parser.error("world-studio MCP is already registered; inspect it before explicitly removing or updating it")
    for name in ("world-input", "world-write"):
        target = skills_root / name
        if target.exists() or target.is_symlink():
            if not target.is_symlink() or target.resolve() != plugin / "skills" / name:
                parser.error(f"Existing skill would be overwritten: {target}")
    subprocess.run([uv, "sync", "--directory", str(plugin), "--frozen"], check=True)
    if not (plugin / "web/dist/index.html").exists():
        subprocess.run(["npm", "ci"], cwd=plugin / "web", check=True)
        subprocess.run(["npm", "run", "build"], cwd=plugin / "web", check=True)
    subprocess.run(command, check=True)
    skills_root.mkdir(parents=True, exist_ok=True)
    for name in ("world-input", "world-write"):
        target = skills_root / name
        if not target.is_symlink():
            target.symlink_to(plugin / "skills" / name, target_is_directory=True)
    data.mkdir(parents=True, exist_ok=True)
    os.chmod(data, 0o700)
    print(json.dumps({**actions, "status": "installed", "next": "Start a new Codex task to load the skills and tools."}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
