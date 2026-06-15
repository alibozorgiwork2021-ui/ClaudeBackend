# ClaudeBackend Dashboard (`ui/`)

A local, **air-gapped** React + TypeScript + Vite dashboard for the `claudebackend serve`
SSE server. It is **fully decoupled** from the Python package: its own `package.json`, its
own build, and it is **never bundled into the wheel** (`pyproject.toml` packages only
`claudebackend`; `node_modules/` and `dist/` are git-ignored).

## What it shows

- **Launch** — start a Planner→Coder→Verifier run (repo path, objective, provider/model,
  language auto/python/php, dry-run toggle).
- **Live** — stage tracker, per-step list (running / retry / security-reject / done /
  failed), live token + cost counters, and a cost sparkline, all driven by Server-Sent
  Events through a pure reducer.
- **Topology** — the dependency graph (`vis-network`), colored by node kind (incl. PHP).
- **Diff** — the dry-run preview diff; security-blocked files are shown as "not written".
- **Review** — approve/reject `CLAUDEBACKEND-REVIEW` files. A reject calls the review
  endpoint, which reverts on the isolated feature branch — the UI never writes files and
  never touches `main`/`master`.

## Develop

```bash
# 1. Start the backend (separate terminal):
pip install -e ".[web]"
claudebackend serve            # loopback :8765

# 2. Start the UI dev server (proxies /api -> 127.0.0.1:8765):
cd ui
npm install
npm run dev                    # http://127.0.0.1:5173
```

## Verify

```bash
npm run test        # Vitest (offline; mocks fetch + EventSource + vis-network)
npm run typecheck   # tsc --noEmit
npm run build       # -> ui/dist (self-contained; no CDN)
```

## Single-process / production

```bash
npm run build
claudebackend serve --ui-dir ui/dist   # serves the built SPA at /
```

All dependencies are bundled at build time — the running app makes no CDN or third-party
requests; it talks only to the local serve API.
