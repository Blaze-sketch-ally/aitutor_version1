import os
import sys

# Ensures `agents`, `services`, `models`, etc. are importable when pytest
# is invoked from a different working directory than the repo root.
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)
