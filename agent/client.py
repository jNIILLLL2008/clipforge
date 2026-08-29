"""
client.py -- Talking to the server.

Every call carries the agent token and nothing else. The agent has no session,
no cookies and no account of its own: the token is the whole of its identity,
which is what makes it revocable from the website in one click.

Network errors are returned rather than raised wherever a caller can sensibly
carry on. A subscriber's laptop loses its connection all the time, and an agent
that dies on the first timeout is useless.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

from .config import AgentConfig

#: A render can take minutes, but every call here is small. A long timeout only
#: hides a dead connection.
TIMEOUT = 30
#: The finished video is the one big upload, so it gets its own budget.
UPLOAD_TIMEOUT = 600


class ServerError(RuntimeError):
    """The server answered, and the answer was no."""


class AuthError(ServerError):
    """The token was rejected.

    Separate from ServerError because it is the one failure the agent can fix
    by itself: a rejected token means this machine needs pairing again, which
    is exactly what pairing is for. Everything else needs a person.
    """


class Server:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {config.token}"
        # So the server can tell us when this build is behind its pipeline.
        from . import PIPELINE_VERSION, __version__

        self.session.headers["X-ClipForge-Pipeline"] = str(PIPELINE_VERSION)
        self.session.headers["User-Agent"] = f"ClipForgeAgent/{__version__}"

    def _url(self, path: str) -> str:
        return f"{self.config.server}{path}"

    # ------------------------------------------------------------------ #
    # Pairing
    # ------------------------------------------------------------------ #
    def hello(self) -> dict:
        """Check the token before starting to poll, so a typo is obvious."""
        response = self.session.get(self._url("/api/agent/hello"),
                                    timeout=TIMEOUT)
        if response.status_code == 401:
            raise AuthError(
                "The server rejected this agent's token. It was most likely "
                "unpaired on the website."
            )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------ #
    # Work
    # ------------------------------------------------------------------ #
    def claim(self) -> Optional[dict]:
        """Ask for a job. None means there is nothing queued right now."""
        response = self.session.post(self._url("/api/agent/claim"),
                                     timeout=TIMEOUT)
        if response.status_code == 204:
            return None
        if response.status_code == 401:
            raise AuthError(
                "This agent's token is no longer valid. Unpaired on the "
                "website, most likely. Start the agent again and it will pair."
            )
        response.raise_for_status()
        return response.json()

    def progress(self, job: str, stage: str, detail: str) -> None:
        """Report a stage. Never fatal: losing a progress line is not a reason
        to abandon a render that is otherwise going fine."""
        try:
            self.session.post(self._url(f"/api/agent/jobs/{job}/progress"),
                              json={"stage": stage, "detail": detail},
                              timeout=TIMEOUT)
        except requests.RequestException:
            pass

    def failed(self, job: str, error: str, rejected: bool = False) -> None:
        self.session.post(self._url(f"/api/agent/jobs/{job}/failed"),
                          json={"error": error[:2000], "rejected": rejected},
                          timeout=TIMEOUT)

    def complete(self, job: str, result: dict, video: Path,
                 thumbnail: Optional[Path] = None) -> dict:
        """Hand back the finished render.

        The file is streamed from disk rather than read into memory: a long
        compilation is tens of MB and this runs on someone's laptop.
        """
        files = {}
        handles = []
        try:
            handle = video.open("rb")
            handles.append(handle)
            files["video"] = (video.name, handle, "video/mp4")
            if thumbnail and thumbnail.is_file():
                thumb = thumbnail.open("rb")
                handles.append(thumb)
                files["thumbnail"] = (thumbnail.name, thumb, "image/jpeg")

            response = self.session.post(
                self._url(f"/api/agent/jobs/{job}/complete"),
                data={"result": json.dumps(result)},
                files=files,
                timeout=UPLOAD_TIMEOUT,
            )
        finally:
            for handle in handles:
                handle.close()

        if response.status_code == 409:
            raise ServerError("The server had already finished this job.")
        response.raise_for_status()
        return response.json()
