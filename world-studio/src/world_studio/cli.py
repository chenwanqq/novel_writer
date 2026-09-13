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
    parser.add_argument("command", choices=["doctor", "serve"], default="doctor", nargs="?")
    args = parser.parse_args()
    if args.command == "serve":
        from .http import serve
        from .repository import Repository
        serve(Repository(args.data), args.port)
        return
    print(json.dumps({"version": __version__, "data": str(data_path(args.data)),
                      "status": "ready"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
