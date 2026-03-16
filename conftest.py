"""Add the repo root to sys.path so custom_components is importable."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
