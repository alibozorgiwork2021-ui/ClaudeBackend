print "loading mathutils"


def halve(n):
    # Python 2 integer division floors; a correct migration must use // to
    # preserve halve(7) == 3 (not 3.5).
    return n / 2


def keys_of(d):
    # Python 2: returns a list (indexable). Python 3: returns a dict_keys view
    # (NOT indexable). The breakage shows up in app.py, which indexes the result
    # -- a genuine cross-file / "orphan file" case.
    return d.keys()
