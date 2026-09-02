"""
config.py -- What the render agent needs to know.

Nothing here is mandatory any more. The server has a default, and the token is
written by the pairing flow rather than pasted in by hand -- see pairing.py for
why. Everything else has a sane default too, because this is installed by a
subscriber on their own machine and every extra question is one more thing they
can get wrong.

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

#: The hosted service. Baked in so a subscriber who downloads the .exe and
#: double-clicks it has nothing to configure at all; anyone running their own
#: instance overrides it with CLIPFORGE_SERVER, in agent.env or the
#: environment, exactly as before.
DEFAULT_SERVER = "https://clipforgee.app"


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


def load(path: Path = DEFAULT_FILE, require_token: bool = True) -> AgentConfig:
    """Read the configuration.

    ``require_token`` is False during startup, when an empty token is not an
    error but the signal to go and pair. It stays True everywhere that is
    about to make a request, so nothing reaches the server holding "".
    """
    values = {**_read_file(path), **os.environ}

    def get(key: str, default: str = "") -> str:
        return str(values.get(key, default)).strip()

    server = get("CLIPFORGE_SERVER", DEFAULT_SERVER).rstrip("/")
    token = get("CLIPFORGE_AGENT_TOKEN")
    if not token and require_token:
        raise SystemExit(
            f"This agent is not paired yet. Run it with no arguments and it "
            f"will open your browser to pair, or set CLIPFORGE_AGENT_TOKEN in "
            f"{path} by hand."
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


def save_pairing(server: str, token: str, path: Path = DEFAULT_FILE) -> Path:
    """Write what pairing produced, keeping anything already in the file.

    Rewriting the file rather than appending means running the flow twice does
    not leave two CLIPFORGE_AGENT_TOKEN lines, where the winner depends on
    parse order. Existing settings the person chose are preserved, in the file
    they put them in.
    """
    values = _read_file(path)
    values["CLIPFORGE_SERVER"] = server.rstrip("/")
    values["CLIPFORGE_AGENT_TOKEN"] = token

    lines = [
        "# Written by the agent when you paired it. Delete the token line and",
        "# run the agent again to pair a different account.",
        "",
    ]
    lines += [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # The token is a credential sitting in a home directory. On anything with
    # POSIX permissions, keep it to the owner; Windows ignores this and relies
    # on the user profile's own ACL, which is the same guarantee.
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def clear_token(path: Path = DEFAULT_FILE) -> None:
    """Forget the token so the next run pairs again."""
    values = _read_file(path)
    values.pop("CLIPFORGE_AGENT_TOKEN", None)
    if not values:
        path.unlink(missing_ok=True)
        return
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8")


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
