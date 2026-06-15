from mathutils import halve, keys_of

HALF = halve(7)

# keys_of returns a dict_keys view in Python 3; indexing it with [0] raises
# TypeError unless the migration is dependency-aware (sees keys_of's body and
# fixes either this call site or keys_of itself). This is the orphan-file proof.
FIRST_KEY = keys_of({"only": 1})[0]

print "half", HALF
print "first key", FIRST_KEY

try:
    raise ValueError("demo")
except ValueError, e:
    print "caught", e
