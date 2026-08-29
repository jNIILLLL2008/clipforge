# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the ClipForge render agent.

Build with:   python agent/build_exe.py
Output:       agent/ClipForgeAgent.exe

Notes
-----
* ffmpeg is NOT bundled. It is a ~90MB pair of binaries that the user is better
  off installing themselves (winget install Gyan.FFmpeg), and the agent checks
  for it on --check and says so if it is missing.
* yt_dlp resolves its extractors dynamically, so they have to be collected by
  name or the YouTube source silently finds nothing in a frozen build.
* The agent imports the render pipeline from backend.app, but nothing that
  serves HTTP. The excludes below are the server's half of the repo: bundling
  SQLAlchemy, FastAPI, Stripe and the Google client would roughly double the
  download for code that never runs here.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent

datas = collect_data_files("yt_dlp")
datas += collect_data_files("certifi")

hiddenimports = collect_submodules("yt_dlp.extractor")
hiddenimports += [
    "agent.main",
    "agent.runner",
    "agent.client",
    "agent.config",
    # yt_dlp and the source adapters are imported inside functions so the
    # server can start without them, which hides them from static analysis.
    "yt_dlp",
    "backend.app.settings_schema",
    "backend.app.sources.upload",
    "backend.app.sources.youtube_source",
    "backend.app.render.pipeline",
    "backend.app.render.engine",
    "backend.app.render.overlay",
    "backend.app.render.retention",
    "backend.app.render.selection",
    "backend.app.render.preview",
    # Optional at runtime: lets yt_dlp present a real browser TLS fingerprint.
    "curl_cffi",
]

a = Analysis(
    [str(ROOT / "agent" / "_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # The server half. None of it is reachable from the agent.
        "sqlalchemy", "fastapi", "starlette", "uvicorn", "stripe",
        "anthropic", "googleapiclient", "google", "google_auth_oauthlib",
        "psycopg", "psycopg2", "multipart",
        # Never pulled in, but PyInstaller will happily bundle them if some
        # dependency mentions them.
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "notebook", "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ClipForgeAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # A console build on purpose. This reports what it is doing and why a run
    # failed; a windowed build would hide exactly the output that matters.
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)
