"""Language-driver registry.

``get_driver(name)`` returns a (cached, stateless) driver instance. Drivers are
registered here; new languages add an entry. Auto-detection (``detect_lang``) and
the ``--lang`` CLI flag arrive with the PHP driver.
"""

from __future__ import annotations

from pathlib import Path

from claudebackend.core.drivers.base import (
    NO_TESTS,
    LanguageDriver,
    SastFinding,
    SyntaxCheck,
    TestRun,
    VerifyStep,
)
from claudebackend.core.drivers.php import PHPDriver
from claudebackend.core.drivers.python import PythonDriver

__all__ = [
    "LanguageDriver",
    "SastFinding",
    "SyntaxCheck",
    "TestRun",
    "VerifyStep",
    "NO_TESTS",
    "PythonDriver",
    "PHPDriver",
    "get_driver",
    "detect_lang",
]

_DRIVERS: dict[str, type[LanguageDriver]] = {
    "python": PythonDriver,
    "php": PHPDriver,
}

_INSTANCES: dict[str, LanguageDriver] = {}


def get_driver(name: str) -> LanguageDriver:
    """Return the (cached) driver for ``name``; raise ``ValueError`` if unknown."""
    if name not in _DRIVERS:
        known = ", ".join(sorted(_DRIVERS))
        raise ValueError(f"unknown language driver: {name!r} (known: {known})")
    if name not in _INSTANCES:
        _INSTANCES[name] = _DRIVERS[name]()
    return _INSTANCES[name]


def detect_lang(root) -> str:
    """Pick a language for a repo when ``--lang`` is left at ``auto``.

    Manifest first (``composer.json`` -> php; ``pyproject.toml``/``requirements.txt``
    -> python), then a source-extension majority across registered drivers. Ties and
    empty repos default to python (the original, backward-compatible behaviour).
    """
    root = Path(root)
    if (root / "composer.json").exists():
        return "php"
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return "python"
    counts: dict[str, int] = {}
    for name in _DRIVERS:
        drv = get_driver(name)
        counts[name] = sum(
            1 for ext in drv.source_exts for _ in root.rglob(f"*{ext}")
        )
    if counts.get("php", 0) > counts.get("python", 0):
        return "php"
    return "python"
