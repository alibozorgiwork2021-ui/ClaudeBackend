from claudebackend import watcher


def test_run_once_green_does_not_develop(monkeypatch):
    monkeypatch.setattr(watcher, "find_first_failure", lambda root: None)
    developed = {"called": False}
    monkeypatch.setattr(
        watcher, "develop_feature",
        lambda *a, **k: developed.__setitem__("called", True),
    )

    assert watcher.run_once("/x") == "green"
    assert developed["called"] is False  # nothing to do when the suite is green


def test_run_once_fixes_in_place(monkeypatch):
    # First check fails, second check (after the fix) passes.
    results = iter([("tests/t.py::test_x", "TRACE"), None])
    monkeypatch.setattr(watcher, "find_first_failure", lambda root: next(results))
    monkeypatch.setattr(watcher, "Client", lambda: object())
    seen = {}

    def fake_dev(root, **kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(watcher, "develop_feature", fake_dev)

    assert watcher.run_once("/x") == "fixed"
    assert seen["apply_in_place"] is True
    assert seen["assume_yes"] is True
    assert seen["task_context"] == "TRACE"


def test_run_once_unfixed_halts(monkeypatch):
    failure = ("tests/t.py::test_x", "TRACE")
    monkeypatch.setattr(watcher, "find_first_failure", lambda root: failure)  # always red
    monkeypatch.setattr(watcher, "Client", lambda: object())
    monkeypatch.setattr(watcher, "develop_feature", lambda root, **kw: object())

    assert watcher.run_once("/x") == "unfixed"
