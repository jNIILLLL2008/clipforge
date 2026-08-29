"""
pairing.py -- Get a token without asking anyone to type one.

The agent used to need a token in a file before it would start, and the token
came off a web page. That install has four places to fail before anything runs:
finding the folder, creating a file with no extension, pasting a 48-character
secret intact, and opening a terminal. Subscribers are not developers and
should not have to be.

So the agent asks for itself. It opens the browser at a page carrying a short
code, waits while the person clicks one button on a site they are already
signed in to, and writes its own config file with what comes back. The token is
never displayed, never copied and never typed.

This is the shape a television uses to sign in, and the reason is the same: the
device has no keyboard worth using, and the browser has the session already.
"""

from __future__ import annotations

import logging
import socket
import time
import webbrowser
from typing import Optional

import requests

log = logging.getLogger("agent.pairing")

#: Give up rather than poll forever. The server expires a code at fifteen
#: minutes, so this only ever ends a wait the server has already ended.
DEADLINE_SECONDS = 15 * 60


def machine_name() -> str:
    """Something the approval page can show, so the person knows it is theirs.

    Never fatal: an agent that cannot name itself still pairs, it just shows
    up as "a computer" on the page.
    """
    try:
        name = socket.gethostname().strip()
    except Exception:  # noqa: BLE001 - a hostname is a nicety, not a requirement
        name = ""
    return name[:120] or "a computer"


class PairingError(RuntimeError):
    """Pairing did not finish. The message is written to be read by the user."""


def _post(server: str, path: str, payload: dict) -> dict:
    try:
        response = requests.post(f"{server}{path}", json=payload, timeout=20)
    except requests.RequestException as exc:
        raise PairingError(f"Could not reach {server}: {exc}") from exc
    if response.status_code == 429:
        raise PairingError(
            "The server is asking us to slow down. Wait a minute and run this "
            "again.")
    if response.status_code >= 400:
        raise PairingError(
            f"The server refused the request ({response.status_code}). "
            f"Check that {server} is the site you subscribed to.")
    try:
        return response.json()
    except ValueError as exc:
        raise PairingError(
            f"{server} did not answer like ClipForge. Check the address.") from exc


def _announce(code: str, url: str, opened: bool) -> None:
    """Say the same thing twice, because the browser may not have opened.

    A headless machine, a locked-down desktop or a Windows default browser that
    has never been set will all leave webbrowser.open silently useless, and the
    person is then staring at a window with no idea what it wants.
    """
    line = "=" * 58
    print()
    print(line)
    if opened:
        print("  Your browser should have opened. If it did not, go to:")
    else:
        print("  Open this page in your browser to finish pairing:")
    print(f"    {url}")
    print()
    print(f"  It will ask you to confirm this code:   {code}")
    print()
    print("  Waiting for you to approve it...")
    print(line)
    print()


def pair(server: str, open_browser: bool = True) -> str:
    """Run the pairing flow start to finish and return the agent token."""
    server = server.rstrip("/")

    started = _post(server, "/api/agent/pair/start", {"label": machine_name()})
    code = started.get("code", "")
    secret = started.get("device_secret", "")
    url = started.get("verify_url", "")
    interval = max(2.0, float(started.get("interval") or 3))
    if not code or not secret or not url:
        raise PairingError(f"{server} did not return a usable pairing code.")

    opened = False
    if open_browser:
        try:
            opened = bool(webbrowser.open(url))
        except Exception:  # noqa: BLE001 - no browser is a nuisance, not a failure
            opened = False
    _announce(code, url, opened)

    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            answer = _post(server, "/api/agent/pair/poll",
                           {"device_secret": secret})
        except PairingError as exc:
            # One refused poll is usually a dropped connection, and the person
            # is watching a window that must not give up on the first blip.
            log.debug("Poll failed, retrying: %s", exc)
            continue

        state = answer.get("status")
        if state == "approved":
            token = answer.get("token", "")
            if not token:
                raise PairingError("The server approved the pairing but sent "
                                   "no token. Try again.")
            who = answer.get("email") or "your account"
            print(f"  Paired with {who}.\n")
            return token
        if state == "expired":
            raise PairingError(
                f"The code {code} expired before it was approved. Run this "
                "again to get a new one.")

    raise PairingError(
        f"Nobody approved {code} within 15 minutes. Run this again when you "
        "are ready.")


def pair_and_save(server: str, save, open_browser: bool = True) -> Optional[str]:
    """Pair, then hand the token to ``save``. None if the user gave up."""
    try:
        token = pair(server, open_browser=open_browser)
    except PairingError as exc:
        log.error("%s", exc)
        return None
    except KeyboardInterrupt:
        print("\n  Cancelled.\n")
        return None
    save(server, token)
    return token
