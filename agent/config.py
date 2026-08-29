"""
config.py -- What the render agent needs to know.

Two things are mandatory: which server to work for, and the token proving which
account it works for. Everything else has a sane default, because this is
installed by a subscriber on their own machine and every extra question is one
more thing they can get wrong.

Read from agent.env beside this file, or from the environment, in that order.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


def _here() -> Path:
    """The folder the agent should read and write beside.

    A PyInstaller onefile build unpacks itself into a temporary directory and
    deletes it on exit, so __file__ points somewhere that will not exist next
    run. Anything the user owns has to sit next to the .exe instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


HERE = _here()
DEFAULT_FILE = HERE / "agent.env"


def _read_file(path: Path) -> Dict[str, str]:
    """Parse a KEY=value file. Absent is fine; malformed lines are skipped."""
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass
class AgentConfig:
    server: str
    token: str
    footage_dir: Path
    work_dir: Path
    poll_seconds: float
    idle_seconds: float

    @property
    def storage_dir(self) -> Path:
        """Where the shared pipeline code expects to find things.

        The pipeline reads uploads from ``<storage>/uploads/<user id>``. The
        agent only ever works for one account, so it presents the local footage
        folder as user 1 and never has to know the real id.
        """
        return self.work_dir / "storage"


def load(path: Path = DEFAULT_FILE) -> AgentConfig:
    values = {**_read_file(path), **os.environ}

    def get(key: str, default: str = "") -> str:
        return str(values.get(key, default)).strip()

    server = get("CLIPFORGE_SERVER").rstrip("/")
    token = get("CLIPFORGE_AGENT_TOKEN")
    if not server or not token:
        raise SystemExit(
            f"Set CLIPFORGE_SERVER and CLIPFORGE_AGENT_TOKEN in {path}.\n"
            "Both come from Settings on the website: pair a render agent and "
            "it shows you the token once."
        )

    work = Path(get("CLIPFORGE_WORK_DIR", str(HERE / "work"))).expanduser()
    footage = Path(get("CLIPFORGE_FOOTAGE_DIR",
                       str(HERE / "footage"))).expanduser()

    return AgentConfig(
        server=server,
        token=token,
        footage_dir=footage,
        work_dir=work,
        # How often to ask for work, and how long to wait after being told
        # there is none. Idle polling is the common case, so it is slower.
        poll_seconds=float(get("CLIPFORGE_POLL_SECONDS", "5") or 5),
        idle_seconds=float(get("CLIPFORGE_IDLE_SECONDS", "20") or 20),
    )


def apply_paths(config: AgentConfig) -> None:
    """Point the shared pipeline at local directories.

    This has to run before anything imports backend.app.config, which reads
    its paths once at import time.
    """
    config.footage_dir.mkdir(parents=True, exist_ok=True)
    uploads = config.storage_dir / "uploads" / "1"
    uploads.mkdir(parents=True, exist_ok=True)

    os.environ["STORAGE_DIR"] = str(config.storage_dir)
    # The agent renders; it never serves the API, so nothing else should try.
    os.environ.setdefault("RENDER_WORKERS", "0")
    os.environ.setdefault("RUN_SCHEDULER", "false")
    # The pipeline refuses sources that are not cleared for reuse unless this
    # is set. On a subscriber's own machine, for their own channel, that is
    # their call to make rather than the server's.
    os.environ.setdefault("ALLOW_UNLICENSED_SOURCES", "true")
    os.environ.setdefault("ENABLED_SOURCES", "upload,youtube")
