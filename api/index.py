"""Vercel entrypoint. Vercel's Python runtime serves a module-level WSGI `app`.

The real application lives in ../app.py so it stays runnable locally as
`python app.py`; this file only puts the repo root on sys.path and re-exports it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402,F401  (Vercel looks for this name)
