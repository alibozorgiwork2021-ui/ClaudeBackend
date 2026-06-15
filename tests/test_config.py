from claudebackend.config import ROLES, resolve_models

try:
    import tomllib  # noqa: F401

    HAVE_TOML = True
except ModuleNotFoundError:
    HAVE_TOML = False


def _clear_env(monkeypatch):
    for r in ROLES:
        monkeypatch.delenv("CLAUDEBACKEND_MODEL_" + r.upper(), raising=False)


def test_defaults_to_default_model(monkeypatch):
    _clear_env(monkeypatch)
    out = resolve_models(default_model="base", root=None)
    assert out == {"planner": "base", "coder": "base", "verifier": "base"}


def test_unset_with_no_default_is_none(monkeypatch):
    _clear_env(monkeypatch)
    out = resolve_models(default_model=None, root=None)
    assert out == {"planner": None, "coder": None, "verifier": None}


def test_cli_override_beats_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CLAUDEBACKEND_MODEL_PLANNER", "env-planner")
    out = resolve_models(
        default_model="base", cli_overrides={"planner": "cli-planner"}, root=None
    )
    assert out["planner"] == "cli-planner"


def test_env_beats_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CLAUDEBACKEND_MODEL_CODER", "env-coder")
    out = resolve_models(default_model="base", root=None)
    assert out["coder"] == "env-coder"
    assert out["planner"] == "base"


def test_pyproject_models(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.claudebackend.models]\n"
        'planner = "pp-planner"\n'
        'coder = "pp-coder"\n',
        encoding="utf-8",
    )
    out = resolve_models(default_model="base", root=tmp_path)
    if HAVE_TOML:
        assert out["planner"] == "pp-planner"
        assert out["coder"] == "pp-coder"
    else:  # 3.10 without tomllib: pyproject is skipped, default applies
        assert out["planner"] == "base"
    assert out["verifier"] == "base"  # unset role falls back to default
