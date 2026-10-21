import os
import sys

# Ensure the project root is importable (tests import `src.*`), so that
# `pytest -q` works exactly as documented in README.md from the project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
