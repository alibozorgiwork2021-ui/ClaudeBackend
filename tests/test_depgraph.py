from claudebackend.core.depgraph import (
    build_graph,
    extract_imports,
    graph_summary,
    ordered_units,
)


# --- extract_imports: must tolerate Python 2 source (D1) ---


def test_extract_imports_from_py2_print():
    # The D1 regression test: ast.parse() raises SyntaxError here; tokenize must not.
    src = b'import os\nprint "hello"\n'
    assert extract_imports(src) == {"os"}


def test_extract_imports_except_comma():
    src = b"import sys\ntry:\n    pass\nexcept ValueError, e:\n    print e\n"
    assert extract_imports(src) == {"sys"}


def test_extract_imports_from_and_aliases():
    src = b"from a.b import c\nimport d as e, f\n"
    assert extract_imports(src) == {"a.b", "d", "f"}


def test_extract_imports_tolerates_unclosed_eof():
    # Imports are tokenized before the unterminated construct at EOF.
    src = b"import json\nx = (\n"
    assert "json" in extract_imports(src)


def test_extract_imports_ignores_word_in_string():
    src = b's = "import nothing here"\nimport real\n'
    assert extract_imports(src) == {"real"}


# --- build_graph: intra-repo edges, stdlib ignored, dynamic flagged ---


def test_build_graph_edges_and_ignores_stdlib(tmp_path):
    (tmp_path / "mathutils.py").write_bytes(b"def halve(n):\n    return n / 2\n")
    (tmp_path / "app.py").write_bytes(
        b"import os\nfrom mathutils import halve\nprint halve(7)\n"
    )
    g = build_graph(tmp_path)
    assert g.edges["app.py"] == {"mathutils.py"}  # os ignored (stdlib)
    assert g.edges["mathutils.py"] == set()


def test_build_graph_flags_dynamic_imports(tmp_path):
    (tmp_path / "d.py").write_bytes(
        b'import importlib\nm = importlib.import_module("x")\n'
    )
    g = build_graph(tmp_path)
    assert "d.py" in g.dynamic


def test_build_graph_resolves_relative_import(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_bytes(b"")
    (pkg / "util.py").write_bytes(b"def f():\n    return 1\n")
    (pkg / "main.py").write_bytes(b"from .util import f\nprint f()\n")
    g = build_graph(tmp_path)
    assert "pkg/util.py" in g.edges["pkg/main.py"]


# --- ordered_units: dependency order + SCC collapse ---


def test_ordered_units_dependency_order(tmp_path):
    (tmp_path / "b.py").write_bytes(b"x = 1\n")
    (tmp_path / "a.py").write_bytes(b"from b import x\n")
    order = ordered_units(build_graph(tmp_path))
    flat = [p for group in order for p in group]
    assert flat.index("b.py") < flat.index("a.py")


def test_ordered_units_collapses_cycle(tmp_path):
    (tmp_path / "a.py").write_bytes(b"import b\n")
    (tmp_path / "b.py").write_bytes(b"import a\n")
    order = ordered_units(build_graph(tmp_path))
    both = [grp for grp in order if set(grp) == {"a.py", "b.py"}]
    assert len(both) == 1


# --- expanded graph: ORM / Dockerfile / config awareness ---


def test_django_model_relationship_edge(tmp_path):
    (tmp_path / "authors.py").write_text(
        "from django.db import models\n"
        "class Author(models.Model):\n    name = models.CharField(max_length=10)\n",
        encoding="utf-8",
    )
    (tmp_path / "books.py").write_text(
        "from django.db import models\n"
        'class Book(models.Model):\n'
        '    author = models.ForeignKey("Author", on_delete=models.CASCADE)\n',
        encoding="utf-8",
    )
    g = build_graph(tmp_path)
    assert g.kinds["authors.py"] == "orm"
    assert g.kinds["books.py"] == "orm"
    # the FK string reference resolves to the model's defining file
    assert "authors.py" in g.edges["books.py"]


def test_sqlalchemy_relationship_edge(tmp_path):
    (tmp_path / "user.py").write_text(
        "class User(Base):\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "post.py").write_text(
        'class Post(Base):\n    user = relationship("User")\n', encoding="utf-8"
    )
    g = build_graph(tmp_path)
    assert g.kinds["user.py"] == "orm"
    assert "user.py" in g.edges["post.py"]


def test_pydantic_base_is_not_orm(tmp_path):
    (tmp_path / "schema.py").write_text(
        "from pydantic import BaseModel\nclass S(BaseModel):\n    x: int\n",
        encoding="utf-8",
    )
    g = build_graph(tmp_path)
    assert g.kinds["schema.py"] == "python"  # BaseModel is not an ORM base


def test_dockerfile_copy_edges(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12\nCOPY requirements.txt .\nCOPY app.py /app/app.py\n",
        encoding="utf-8",
    )
    g = build_graph(tmp_path)
    assert g.kinds["Dockerfile"] == "dockerfile"
    assert "requirements.txt" in g.edges["Dockerfile"]
    assert "app.py" in g.edges["Dockerfile"]


def test_config_module_reference_edge(tmp_path):
    (tmp_path / "tasks.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("worker:\n  module: tasks\n", encoding="utf-8")
    g = build_graph(tmp_path)
    assert g.kinds["config.yaml"] == "config"
    assert "tasks.py" in g.edges["config.yaml"]


def test_graph_summary_groups_by_kind(tmp_path):
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    summary = graph_summary(build_graph(tmp_path))
    assert "Python modules:" in summary
    assert "a.py -> b.py" in summary
