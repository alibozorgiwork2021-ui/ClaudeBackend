"""Render the codebase topology as ``DEV_GRAPH.md`` + interactive ``graph.html``.

The HTML pulls vis-network from a CDN and is otherwise self-contained. Nodes are
grouped/coloured by kind (Python module / ORM model / Dockerfile / Config) and
edges are coloured by the source node's kind (import / model-rel / docker-copy /
config-ref). The legend reflects standard project topology — modules and their
dependencies — not migration units.
"""

from __future__ import annotations

import json
from pathlib import Path

from claudebackend.core.depgraph import Graph, graph_summary

_KIND_LABEL = {
    "python": "Python module",
    "php": "PHP module",
    "orm": "ORM model",
    "dockerfile": "Dockerfile",
    "config": "Config",
}
_KIND_COLOR = {
    "python": "#4f86c6",
    "php": "#777bb3",
    "orm": "#7b5cb8",
    "dockerfile": "#2496ed",
    "config": "#e09f3e",
}
_EDGE_LABEL = {
    "python": "import",
    "php": "import",
    "orm": "model-rel",
    "dockerfile": "docker-copy",
    "config": "config-ref",
}
_ORDER = ("python", "php", "orm", "dockerfile", "config")

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ClaudeBackend - project topology</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #1e1e2e; color: #eee; }
  #graph { width: 100vw; height: 100vh; }
  #legend { position: fixed; top: 12px; left: 12px; background: rgba(30,30,46,.92);
            padding: 10px 14px; border-radius: 8px; font-size: 13px; line-height: 1.4; }
  #legend h3 { margin: 0 0 6px; font-size: 13px; }
  .row { display: flex; align-items: center; margin: 3px 0; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; margin-right: 8px; }
</style>
</head>
<body>
<div id="legend">__LEGEND__</div>
<div id="graph"></div>
<script>
  const nodes = new vis.DataSet(__NODES__);
  const edges = new vis.DataSet(__EDGES__);
  const container = document.getElementById('graph');
  const options = {
    nodes: { shape: 'dot', size: 14, font: { color: '#eee' } },
    edges: { smooth: { type: 'continuous' }, color: { opacity: 0.6 } },
    physics: { stabilization: true, barnesHut: { gravitationalConstant: -8000 } },
    interaction: { hover: true, tooltipDelay: 120 }
  };
  new vis.Network(container, { nodes, edges }, options);
</script>
</body>
</html>
"""


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _nodes_edges(graph: Graph) -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "id": path,
            "label": _basename(path),
            "title": path,
            "group": graph.kinds.get(path, "python"),
            "color": _KIND_COLOR.get(graph.kinds.get(path, "python"), "#888888"),
        }
        for path in sorted(graph.kinds)
    ]
    known = set(graph.kinds)
    edges = []
    for path in sorted(graph.edges):
        kind = graph.kinds.get(path, "python")
        for dep in sorted(graph.edges[path]):
            if dep not in known:
                continue
            edges.append(
                {
                    "from": path,
                    "to": dep,
                    "arrows": "to",
                    "color": {"color": _KIND_COLOR.get(kind, "#888888")},
                }
            )
    return nodes, edges


def _legend_html(counts: dict[str, int]) -> str:
    rows = ["<h3>Project topology</h3>"]
    for kind in _ORDER:
        if not counts.get(kind):
            continue
        rows.append(
            f'<div class="row"><span class="swatch" style="background:'
            f'{_KIND_COLOR[kind]}"></span>{_KIND_LABEL[kind]} ({counts[kind]}) '
            f'&middot; {_EDGE_LABEL[kind]}</div>'
        )
    return "\n".join(rows)


def _render_md(graph: Graph, counts: dict[str, int], n_edges: int) -> str:
    lines = [
        "# Project topology graph",
        "",
        f"{sum(counts.values())} nodes, {n_edges} edges. "
        "Open `graph.html` for the interactive view.",
        "",
        "## Legend",
    ]
    for kind in _ORDER:
        if counts.get(kind):
            lines.append(
                f"- **{_KIND_LABEL[kind]}** ({counts[kind]}) — edge type: "
                f"`{_EDGE_LABEL[kind]}`"
            )
    summary = graph_summary(graph)
    lines += ["", "## Map", "", "```", summary or "(empty)", "```", ""]
    return "\n".join(lines)


def render_graph(graph: Graph, out_dir) -> tuple[Path, Path]:
    """Write ``DEV_GRAPH.md`` and ``graph.html`` into ``out_dir``; return paths."""
    out_dir = Path(out_dir)
    nodes, edges = _nodes_edges(graph)
    counts: dict[str, int] = {}
    for kind in graph.kinds.values():
        counts[kind] = counts.get(kind, 0) + 1

    md_path = out_dir / "DEV_GRAPH.md"
    md_path.write_text(_render_md(graph, counts, len(edges)), encoding="utf-8")

    html = (
        _HTML_TEMPLATE.replace("__LEGEND__", _legend_html(counts))
        .replace("__NODES__", json.dumps(nodes))
        .replace("__EDGES__", json.dumps(edges))
    )
    html_path = out_dir / "graph.html"
    html_path.write_text(html, encoding="utf-8")
    return md_path, html_path
