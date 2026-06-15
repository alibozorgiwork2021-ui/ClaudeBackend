def test_package_imports():
    import claudebackend  # noqa: F401
    from claudebackend.cli import app

    assert app is not None
