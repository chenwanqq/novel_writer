"""Start the loopback editor from a stdio tool without mixing its logs into MCP stdout."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .repository import Repository, StudioError, encode


def open_atlas(repo: Repository, port: int = 8765) -> dict:
    if not 1024 <= port <= 65535:
        raise StudioError("port", "Choose a local port between 1024 and 65535")
    build = Path(__file__).resolve().parents[2] / "web/dist/index.html"
    if not build.exists():
        raise StudioError("map_build", "Build the editor first: cd world-studio/web && npm ci && npm run build")
    runtime = repo.root / f"runtime-{port}.json"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def alive(info):
        origin, token = info["url"].split('/#token=')
        if origin != f"http://127.0.0.1:{port}" or info.get("data") != str(repo.root):
            return False
        req = urllib.request.Request(origin + '/api/worlds', data=b'{}', headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=1) as response:
                return response.status == 200
        except OSError:
            return False

    if runtime.exists():
        try:
            info = json.loads(runtime.read_text())
            if alive(info):
                return info
        except (ValueError, KeyError):
            pass
    log = repo.root / f"runtime-{port}.log"
    with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as output:
        process = subprocess.Popen([sys.executable, '-m', 'world_studio.cli', '--data', str(repo.root), '--port', str(port), 'serve'],
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StudioError("map_start", "Map server stopped; inspect local runtime log", str(log))
        lines = log.read_text().splitlines()
        url = next((s[5:] for s in lines if s.startswith('Open http://127.0.0.1:')), None)
        if url:
            info = {"url": url, "pid": process.pid, "data": str(repo.root)}
            if alive(info):
                with os.fdopen(os.open(runtime, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as output:
                    output.write(encode(info))
                os.chmod(runtime, 0o600)
                os.chmod(log, 0o600)
                return info
        time.sleep(.1)
    process.terminate()
    raise StudioError("map_timeout", "Map server failed to become ready; inspect local runtime log", str(log))
