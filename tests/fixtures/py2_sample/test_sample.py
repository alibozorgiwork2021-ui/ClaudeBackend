"""Tests the MIGRATED (Python 3) output. Importing ``app`` executes its
module-level code, so a broken cross-file migration fails at import."""

import app
from mathutils import halve


def test_halve_floors_like_py2():
    assert halve(7) == 3


def test_app_half_is_floor_division():
    assert app.HALF == 3


def test_app_first_key_resolved_across_files():
    assert app.FIRST_KEY == "only"
