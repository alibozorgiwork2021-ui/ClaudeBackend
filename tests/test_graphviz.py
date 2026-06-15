from claudebackend.core.depgraph import Graph
from claudebackend.core.graphviz import render_graph


def _graph():
    return Graph(
        edges={"app.py": {"db.py"}, "db.py": set(), "Dockerfile": {"app.py"}},
        kinds={"app.py": "python", "db.py": "orm", "Dockerfile": "dockerfile"},
    )


def test_render_graph_writes_md_and_html(tmp_path):
    md_path, html_path = render_graph(_graph(), tmp_path)

    assert md_path.name == "DEV_GRAPH.md"
    assert html_path.name == "graph.html"

    md = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")

    # Legend reflects standard project topology, not migration units.
    assert "Python module" in md
    assert "ORM model" in md
    assert "Dockerfile" in md
    assert "migration unit" not in md.lower()

    # The HTML is a self-contained vis-network graph with the nodes embedded.
    assert "vis-network" in html
    assert "app.py" in html and "db.py" in html


def test_render_graph_empty_is_valid(tmp_path):
    md_path, html_path = render_graph(Graph(), tmp_path)
    assert md_path.exists() and html_path.exists()
    assert "vis-network" in html_path.read_text(encoding="utf-8")
