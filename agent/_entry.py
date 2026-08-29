"""
_entry.py -- Entry point for the frozen build.

PyInstaller runs its entry script as ``__main__``, which has no parent package,
so the relative imports in ``agent/main.py`` fail with "attempted relative
import with no known parent package". Importing the package properly and
calling into it keeps ``python -m agent.main`` working unchanged while giving
the .exe something it can start from.
"""

from __future__ import annotations

import sys

from agent.main import main

if __name__ == "__main__":
    sys.exit(main())
