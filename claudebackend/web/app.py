"""Starlette application factory for the local dashboard server.

All Starlette imports are inside :func:`create_app` so importing this module never
requires the ``[web]`` extra until a server is actually built. The app exposes a small
JSON + SSE API; it makes no outbound calls of its own (only the per-run LLM client
does, and ``local=True`` keeps that on local Ollama).
"""

from __future__ import annotations

import asyncio
import json
import time

from claudebackend.core import git
from claudebackend.web import serialize
from claudebackend.web.review import ReviewError, apply_review
from claudebackend.web.runs import RunRegistry, start_run


def _default_client_factory(body: dict):
    from claudebackend.core.client import Client

    provider = body.get("provider", "anthropic")
    local = bool(body.get("local"))
    if local and provider == "anthropic":
        provider = "ollama"
    return Client(provider=provider, model=body.get("model"), local=local)


def _sse(frame: dict) -> str:
    return "data: " + json.dumps(frame) + "\n\n"


def create_app(*, registry: RunRegistry | None = None, client_factory=None,
               allow_remote: bool = False, cors_origins=(), ui_dir=None):
    """Build the dashboard Starlette app. ``client_factory(body)`` lets tests inject a
    FakeClient; it defaults to a real ``Client`` built from the request body."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Mount, Route

    registry = registry or RunRegistry()
    client_factory = client_factory or _default_client_factory

    async def health(request):
        return JSONResponse({"ok": True, "air_gapped": True, "allow_remote": allow_remote})

    async def create_run(request):
        body = await request.json()
        path = body.get("path")
        objective = body.get("objective")
        if not path or not objective:
            return JSONResponse(
                {"error": "both 'path' and 'objective' are required"}, status_code=400
            )
        dry_run = bool(body.get("dry_run", True))
        if not dry_run and registry.has_active_run(path):
            return JSONResponse(
                {"error": "a live run is already in progress for this path"},
                status_code=409,
            )
        lang = body.get("lang", "auto")
        if lang == "auto":
            from claudebackend.core.drivers import detect_lang

            lang = detect_lang(path)

        handle = registry.create(path, objective=objective, dry_run=dry_run, lang=lang)
        # The worker captures the revert baseline (after any init) before changing files.
        handle.loop = asyncio.get_running_loop()
        handle.tick = asyncio.Event()

        client = client_factory(body)
        develop_kwargs = {
            "init": bool(body.get("init", False)),
            "security_gate": bool(body.get("security_gate", True)),
            "max_retries": int(body.get("max_retries", 3)),
        }
        start_run(handle, client, develop_kwargs)
        return JSONResponse(
            {"id": handle.id, "status": handle.status, "dry_run": dry_run, "lang": lang},
            status_code=201,
        )

    async def stream_events(request):
        handle = registry.get(request.path_params["run_id"])
        if handle is None:
            return JSONResponse({"error": "unknown run"}, status_code=404)

        async def gen():
            yield _sse(serialize.frame(
                "hello",
                {"run_id": handle.id, "dry_run": handle.dry_run,
                 "objective": handle.objective, "lang": handle.lang,
                 "status": handle.status},
                run_id=handle.id, seq=-1, ts=time.time(),
            ))
            last = 0
            while True:
                while last < len(handle.frames):
                    fr = handle.frames[last]
                    last += 1
                    yield _sse(fr)
                    if fr["type"] in ("done", "error"):
                        return
                try:
                    await asyncio.wait_for(handle.tick.wait(), timeout=15)
                    handle.tick.clear()
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # SSE comment frame keeps the conn warm

        return StreamingResponse(gen(), media_type="text/event-stream")

    async def run_status(request):
        handle = registry.get(request.path_params["run_id"])
        if handle is None:
            return JSONResponse({"error": "unknown run"}, status_code=404)
        return JSONResponse(handle.summary())

    async def run_graph(request):
        handle = registry.get(request.path_params["run_id"])
        if handle is None or handle.graph is None:
            return JSONResponse({"error": "no graph for this run"}, status_code=404)
        return JSONResponse(handle.graph)

    async def run_report(request):
        handle = registry.get(request.path_params["run_id"])
        if handle is None or handle.report is None:
            return JSONResponse({"error": "no report yet"}, status_code=404)
        return JSONResponse(handle.report)

    async def list_runs(request):
        return JSONResponse({"runs": registry.list()})

    async def review_run(request):
        handle = registry.get(request.path_params["run_id"])
        if handle is None:
            return JSONResponse({"error": "unknown run"}, status_code=404)
        body = await request.json()
        try:
            result = apply_review(handle, body.get("decisions", []))
        except ReviewError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except git.GitError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result)

    routes = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/runs", create_run, methods=["POST"]),
        Route("/api/runs", list_runs, methods=["GET"]),
        Route("/api/runs/{run_id}/events", stream_events, methods=["GET"]),
        Route("/api/runs/{run_id}/graph", run_graph, methods=["GET"]),
        Route("/api/runs/{run_id}/report", run_report, methods=["GET"]),
        Route("/api/runs/{run_id}/review", review_run, methods=["POST"]),
        Route("/api/runs/{run_id}", run_status, methods=["GET"]),
    ]
    if ui_dir:
        from starlette.staticfiles import StaticFiles

        routes.append(Mount("/", app=StaticFiles(directory=str(ui_dir), html=True)))

    middleware = []
    if cors_origins:
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware

        middleware.append(Middleware(
            CORSMiddleware, allow_origins=list(cors_origins),
            allow_methods=["*"], allow_headers=["*"],
        ))

    return Starlette(routes=routes, middleware=middleware)
