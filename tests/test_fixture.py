from pathlib import Path

from claudebackend.core.depgraph import build_graph, ordered_units
from claudebackend.core.verifier import verify_file

FIXTURE = Path(__file__).parent / "fixtures" / "py2_sample"


def test_fixture_is_genuine_python2():
    # py_compile under py3 must fail on these files -- they are real py2 source.
    assert verify_file(FIXTURE / "app.py").ok is False
    assert verify_file(FIXTURE / "mathutils.py").ok is False


def test_fixture_depgraph_orders_dependency_first():
    order = ordered_units(build_graph(FIXTURE))
    flat = [p for group in order for p in group]
    assert flat.index("mathutils.py") < flat.index("app.py")
