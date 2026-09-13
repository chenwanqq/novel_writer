"""Command line entry point. JSON output is suitable for troubleshooting."""
import argparse
import json
from . import __version__
from .config import data_path


def main() -> None:
    parser = argparse.ArgumentParser(prog="world-studio")
    parser.add_argument("--data", help="Data directory (or WORLD_STUDIO_DATA)")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--archive", help="Backup ZIP for restore")
    parser.add_argument("--world", help="World ID for export")
    parser.add_argument("--work", help="Work ID for adopted manuscript export")
    parser.add_argument("--revision", help="Pinned revision for export")
    parser.add_argument("command", choices=["doctor", "serve", "mcp", "demo", "backup", "restore", "export"], default="doctor", nargs="?")
    args = parser.parse_args()
    if args.command == "serve":
        from .http import serve
        from .repository import Repository
        serve(Repository(args.data), args.port)
        return
    if args.command == "restore":
        if not args.archive or not args.data:
            parser.error("restore requires --archive and an explicit empty --data destination")
        from .transfer import restore
        print(json.dumps(restore(args.archive, args.data), ensure_ascii=False))
        return
    if args.command != "doctor":
        from .repository import Repository
        repo = Repository(args.data)
        if args.command == "mcp":
            from .server import create_server
            create_server(repo).run(transport="stdio")
            return
        if args.command == "demo":
            from .demo import seed_demo
            result = seed_demo(repo)
        elif args.command == "backup":
            from .transfer import backup
            result = backup(repo)
        else:
            if bool(args.world) == bool(args.work):
                parser.error("export requires exactly one of --world or --work")
            from .transfer import export_markdown, export_work
            result = (export_work(repo, args.work, args.revision) if args.work
                      else export_markdown(repo, args.world, args.revision))
        print(json.dumps(result, ensure_ascii=False))
        return
    print(json.dumps({"version": __version__, "data": str(data_path(args.data)),
                      "status": "ready"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
