# The render agent

Runs ClipForge jobs on your own computer instead of the server.

## Why it exists

YouTube serves datacentre IPs a bot interstitial and answers home connections
normally. A cloud instance gets refused for requests that work fine on a
laptop. The usual fixes are both bad for a paid product: asking a subscriber
for a `cookies.txt` hands over their entire Google session, and a residential
proxy costs roughly $65 a month per Pro subscriber against about $50 of
revenue.

Running the work where the subscriber already is removes the problem instead of
disguising it, and the ffmpeg encode stops being billed to the server.

## What runs where

The agent renders. The server still decides everything else.

| Server | Agent |
| --- | --- |
| Accounts, billing, plan limits | Sourcing footage |
| The monthly allowance | Cutting and encoding |
| The retention verdict, and refunds | Burning in captions and overlays |
| Title, description and tags | Nothing else |
| Uploading to YouTube | |

The agent is handed one job at a time and hands back a file. It cannot create
work for itself, so it does nothing without a live subscription, and the status
it reports cannot mark a job finished on its own.

The finished video is uploaded back rather than published from here. It is a
few MB once, against the tens of GB of source footage the server no longer
pulls, and your channel's refresh token stays on the server.

## Setup

On Windows, put `ClipForgeAgent.exe` in a folder of its own and run it. That
is the whole install.

On a Mac, unpack the `.zip` into a folder of its own, then **right-click**
`Start ClipForge Agent.command` and choose Open. Right-click rather than
double-click, and only the first time: the build is signed ad-hoc, which is
enough for Apple silicon to run it at all, but it is not notarized, and macOS
refuses anything a browser downloaded from a developer it has not seen until
it is opened that way once. The launcher then clears the quarantine flag off
the rest of the folder, so ffmpeg does not need its own approval, and starts
the agent.

That difference is worth spelling out to subscribers rather than hiding,
because macOS words the refusal as *"cannot be opened"* or *"is damaged"*,
which reads as a broken download. It is neither.

On the first run the agent has no token, so it opens your browser at the site,
shows you a short code, and waits. You sign in if you are not already, check
the code matches, and click **Pair it**. The agent picks the token up within a
few seconds, writes its own `agent.env` and starts working. Nothing is copied
and no file is edited by hand.

**ffmpeg is handled for you**, on both. The `.zip` downloads ship it in
`ffmpeg/` beside the agent, so there is nothing to install. Taken on its own,
the agent fetches its own copy into `ffmpeg/` on the first run -- about 110MB
on Windows, 57MB on a Mac, once, with a progress bar, checked against the
checksum the builder publishes. An ffmpeg already on PATH is used as-is and
nothing is downloaded; on a Mac that includes `/opt/homebrew/bin`, which a
program started from Finder cannot see on PATH because it inherits launchd's
and not your shell's. `--no-download` turns the fetch off if you would rather
install it yourself.

A Mac is also the one machine that will fall asleep in the middle of a job, so
the agent holds off idle sleep with `caffeinate` while it is rendering and
stops as soon as the job is done. Closing the lid still sleeps the machine,
which is what closing the lid means.

Drop your own clips in `footage/` beside the agent if you use the upload
source.
Everything the agent reads and writes lives in that one folder, so keep it
together if you move it.

### Why pairing works this way

The old install asked for the token off a web page and into a file. That is
four chances to give up before anything runs -- find the folder, create a file
with no extension, paste a 48-character secret intact, open a terminal -- and
subscribers are not developers. Now the agent asks and the person clicks once.
It is the shape a television uses to sign in, for the same reason.

### From source

You need Python 3.11+. Same flow:

```bash
python -m agent.main     # python3 on a Mac
```

`--check` verifies the token, reports your plan and remaining runs, confirms
ffmpeg and counts the footage it can see, then exits. `--once` takes a single
job and exits, which is what you want from a scheduled task. `--pair` pairs
again with a different account, and `--unpair` forgets the token on this
machine.

An unattended install with no browser can still be configured by hand: copy
`agent.env.example` to `agent.env` and fill in a token minted by pairing
somewhere else.

## Settings

Everything lives in `agent.env`. Only the first two are required.

| Setting | Default | |
| --- | --- | --- |
| `CLIPFORGE_SERVER` | the hosted site | Only needed for your own instance |
| `CLIPFORGE_AGENT_TOKEN` | | Written by pairing; you should not set it |
| `CLIPFORGE_FOOTAGE_DIR` | `./footage` | Your own clips |
| `CLIPFORGE_WORK_DIR` | `./work` | Scratch space, cleaned as it goes |
| `CLIPFORGE_POLL_SECONDS` | `5` | Wait after finishing a job |
| `CLIPFORGE_IDLE_SECONDS` | `20` | Wait when there was nothing to do |

`agent.env`, `footage/` and `work/` are all gitignored. The token is a
credential: anything holding it can claim your jobs. The file is written
`0600` where the filesystem supports it, and revoking it on the website stops
it immediately.

## Building the downloads

```bash
python agent/build_exe.py --clean --bundle     # on Windows
python3 agent/build_mac.py --clean --bundle    # on a Mac
```

Each is around 25MB on its own and lands beside the source, at
`agent/ClipForgeAgent.exe` or `agent/ClipForgeAgent`. `--bundle` produces what
subscribers actually download -- the agent and ffmpeg in one archive:
`agent/ClipForgeAgent-windows.zip` at about 100MB, or
`agent/ClipForgeAgent-macos-arm64.zip` at about 60MB.

Both read the same `ClipForgeAgent.spec`, so the two builds cannot drift in
what they include, and **each has to be built on the platform it is for**.
PyInstaller freezes the interpreter it is running under; there is no
cross-compiling it. For the same reason the Mac build is per-architecture:
`build_mac.py` names the archive after the chip it was built on, so an Apple
silicon and an Intel build can sit in the same release. Macs sold since late
2020 are arm64.

The Windows bundle needs `agent/ffmpeg/` to exist first; run the agent once
and let it fetch one. The Mac build fetches its own if it is missing, through
the same code the agent uses, so a broken download shows up at build time
rather than on a subscriber's machine.

The Mac zip also carries `Start ClipForge Agent.command` and writes every
entry with its permissions set by hand. Python's `zipfile` records none
otherwise, and a binary that arrives without its executable bit is a binary
that will not start.

ffmpeg sits *next to* the agent rather than inside it. Two static binaries
are 130-200MB, and PyInstaller's onefile mode unpacks its entire payload into
a temp directory on every launch -- burying them would write that much to disk
each time a long-running agent starts. The .zip gets the same one-download
install without paying it on every run.

The ffmpeg is GPL on both platforms, because the pipeline encodes with
`libx264` and an LGPL build has no software H.264 encoder at all. That means
each `.zip` must point at the source, which `READ ME FIRST.txt` does; the
Windows archive ships ffmpeg's own `LICENSE` beside the binaries as well,
while the Mac downloads contain nothing but the binary, so the notice in the
READ ME is the whole of it. Both are unmodified upstream builds -- gyan.dev
on Windows, ffmpeg.martin-riedl.de on macOS -- and the agent invokes them as a
separate process, so nothing here makes ClipForge itself a derived work.

The server half of the repo is excluded from the build, so SQLAlchemy, FastAPI,
Stripe and the Google client are not along for the ride. Both builds are
gitignored because they are build artefacts; the spec and the two scripts are
what is kept.

## Where the downloads come from

Set `AGENT_DOWNLOAD_URL` and `AGENT_DOWNLOAD_URL_MAC` on the server to
wherever the builds are published -- a GitHub release, normally -- and the app
shows a download button next to the pairing instructions. It offers whichever
matches the computer the page is being read on, and puts the other underneath
as a link, for somebody setting up a machine they are not sitting at. Either
left unset shows the run-from-source route instead of a button that leads
nowhere.

## How work is shared with the server

You do not have to choose. The server's own render pool stands down for any
account whose agent is *currently polling*, so a running agent gets the work
without a race, and an account with no agent -- or one that is closed -- is
rendered on the server as usual. The handover is automatic in both directions
and takes a couple of minutes at most.

That matters because the two are not interchangeable: YouTube refuses the
server's datacentre address and answers a home connection, so a job that
lands on the server is the one likely to fail.

`AGENT_ONLINE_SECONDS` (default 120) is how long after its last poll an agent
still counts as live. The agent polls every 20 seconds when idle, so that is
six missed polls.

To take the server out entirely and make every job wait for an agent:

```bash
RENDER_WORKERS=0
```

Jobs then queue and wait rather than failing, so a machine asleep at 9am picks
the run up when it wakes. Most instances do not want this -- it means a
subscriber with no agent never gets a video.

## When something goes wrong

The agent reports the real reason rather than a generic failure, and it shows
up in History on the website. The three worth knowing:

- **You have not uploaded any footage yet** -- `footage/` is empty, and the
  niche only uses your own uploads.
- **The YouTube source has nothing to look at** -- the niche needs a channel
  under Source channels, or some search terms.
- **YouTube refused the request** -- rare from a home connection, which is the
  point of running here.

A crash mid-render leaves the job claimed. It is picked up again after a server
restart, and the run is refunded rather than charged.
