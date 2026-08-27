"""Logging shared by the API and the render workers."""

from __future__ import annotations

import logging
import sys
from typing import Optional

_CONFIGURED = False
FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger("clipforge")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"clipforge.{name}" if name else "clipforge")
