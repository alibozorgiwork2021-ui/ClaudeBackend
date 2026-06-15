from claudebackend import tdd


def test_first_failing_nodeid_summary_format():
    out = (
        "F\n=== FAILURES ===\n...\n=== short test summary info ===\n"
        "FAILED tests/test_a.py::test_x - AssertionError: nope\n1 failed in 0.1s"
    )
    assert tdd.first_failing_nodeid(out) == "tests/test_a.py::test_x"


def test_first_failing_nodeid_error_format():
    out = "ERROR tests/test_b.py::test_y - ImportError\n"
    assert tdd.first_failing_nodeid(out) == "tests/test_b.py::test_y"


def test_first_failing_nodeid_none_when_green():
    assert tdd.first_failing_nodeid("3 passed in 0.01s") is None


def test_tdd_objective_mentions_nodeid_and_forbids_modifying_test():
    obj = tdd.tdd_objective("tests/test_a.py::test_x", "TRACEBACK-TEXT")
    assert "tests/test_a.py::test_x" in obj
    assert "do not modify" in obj.lower()
    assert "TRACEBACK-TEXT" in obj


def test_find_first_failure_green(monkeypatch):
    monkeypatch.setattr(tdd, "run_pytest", lambda root: (0, "5 passed"))
    assert tdd.find_first_failure("/x") is None


def test_find_first_failure_no_tests_collected(monkeypatch):
    monkeypatch.setattr(tdd, "run_pytest", lambda root: (5, "no tests ran"))
    assert tdd.find_first_failure("/x") is None


def test_find_first_failure_returns_nodeid_and_output(monkeypatch):
    out = "FAILED tests/test_a.py::test_x - AssertionError\n1 failed in 0.1s"
    monkeypatch.setattr(tdd, "run_pytest", lambda root: (1, out))
    assert tdd.find_first_failure("/x") == ("tests/test_a.py::test_x", out.strip())
