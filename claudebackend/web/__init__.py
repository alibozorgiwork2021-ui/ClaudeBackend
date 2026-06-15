"""Optional local dashboard server (the ``[web]`` extra).

Air-gapped by design: binds loopback only unless ``--allow-remote`` is given, makes no
outbound calls itself, and keeps all run state in memory. The core CLI/MCP never import
this package; it is reached only through ``claudebackend serve``.
"""

from __future__ import annotations

# Note: an empty host means "bind all interfaces", which is NOT loopback — it must
# not be treated as safe.
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _require_web() -> None:
    """Raise a clear, actionable error if the ``[web]`` extra is not installed."""
    try:
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "the dashboard server needs the 'web' extra. Install it with: "
            "pip install claudebackend[web]"
        ) from exc


def _is_loopback(host: str) -> bool:
    return host in _LOOPBACK


def run_server(host: str = "127.0.0.1", port: int = 8765, *,
               allow_remote: bool = False, ui_dir=None, cors_origins=()) -> None:
    """Run the dashboard server (blocking). Refuses a non-loopback bind unless
    ``allow_remote`` is set, preserving the air-gapped default."""
    _require_web()
    if not _is_loopback(host) and not allow_remote:
        raise RuntimeError(
            f"refusing to bind non-loopback host {host!r} without --allow-remote "
            "(the dashboard is air-gapped/loopback-only by default)"
        )
    import uvicorn

    from claudebackend.web.app import create_app

    app = create_app(allow_remote=allow_remote, ui_dir=ui_dir, cors_origins=cors_origins)
    uvicorn.run(app, host=host, port=port, log_level="info")
