"""Loopback-only map server; adapters never write SQL or bypass domain checks."""
import json
import secrets
from pathlib import Path

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .atlas import Atlas, route_query
from .repository import Repository, StudioError


def create_app(repo: Repository, token: str, origin: str = "http://127.0.0.1:8765",
               static: Path | None = None) -> Starlette:
    atlas = Atlas(repo)
    static = static or Path(__file__).resolve().parents[2] / "web/dist"

    def authorize(request: Request) -> bool:
        return (request.headers.get("host") == origin.split("//", 1)[1]
                and request.headers.get("origin", origin) == origin
                and secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token))

    async def call(request: Request):
        if not authorize(request):
            return JSONResponse({"code": "unauthorized", "message": "Open the local token link; cross-origin access is disabled"}, status_code=403)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 30 * 1024 * 1024:
                return JSONResponse({"code": "too_large"}, status_code=413)
        try:
            params = json.loads(data or b"{}")
            if not isinstance(params, dict):
                raise StudioError("request", "Expected a JSON object")
            methods = {
                "worlds": repo.list_worlds, "create_world": repo.create_world,
                "snapshot": repo.snapshot, "head": repo.head, "diff": repo.diff,
                "new_draft": atlas.new_draft, "draft": atlas.draft, "save_draft": atlas.save,
                "propose_map": atlas.proposal, "preview": repo.preview,
                "commit_map": atlas.commit, "rebase_map": atlas.rebase,
                "upload": atlas.upload, "background": atlas.background,
                "route": lambda **kw: route_query(repo, **kw),
                "revisions": lambda world: revisions(repo, world),
            }
            method = methods.get(request.path_params["method"])
            if not method:
                return JSONResponse({"code": "method_missing"}, status_code=404)
            # Synchronous SQLite and image decoding must not block the ASGI event loop.
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(method, **params)
            return JSONResponse({"result": result})
        except StudioError as exc:
            return JSONResponse({"code": exc.code, "message": str(exc), "details": exc.details},
                                status_code=409 if exc.code in ("stale_base", "stale_draft", "merge_conflict") else 400)
        except (TypeError, ValueError, ValidationError) as exc:
            return JSONResponse({"code": "invalid_request", "message": str(exc)}, status_code=400)
        except FileNotFoundError:
            return JSONResponse({"code": "asset_missing", "message": "Referenced file is missing; restore from backup"}, status_code=404)

    async def page(request: Request):
        if request.headers.get("host") != origin.split("//", 1)[1]:
            return Response(status_code=403)
        relative = request.path_params.get("path") or "index.html"
        path = (static / relative).resolve()
        if not path.is_relative_to(static.resolve()) or not path.is_file():
            return Response("Map assets not built. Run npm ci && npm run build in world-studio/web.", status_code=404)
        return FileResponse(path, headers={"Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"})

    return Starlette(routes=[Route("/api/{method}", call, methods=["POST"]), Route("/{path:path}", page)])


def revisions(repo: Repository, world: str) -> list[dict]:
    with repo.connect() as db:
        return [dict(r) for r in db.execute("SELECT id,parent,decision,created FROM revisions WHERE world=? ORDER BY rowid DESC", (world,))]


def serve(repo: Repository, port: int = 8765) -> None:
    import uvicorn
    token = secrets.token_urlsafe(32)
    origin = f"http://127.0.0.1:{port}"
    print(f"Open {origin}/#token={token}", flush=True)
    uvicorn.run(create_app(repo, token, origin), host="127.0.0.1", port=port, access_log=False)
