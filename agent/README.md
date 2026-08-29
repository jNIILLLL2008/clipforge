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

Put `ClipForgeAgent.exe` in a folder of its own and run it. That is the whole
install.

On the first run it has no token, so it opens your browser at the site, shows
you a short code, and waits. You sign in if you are not already, check the code
matches, and click **Pair it**. The agent picks the token up within a few
seconds, writes its own `agent.env` and starts working. Nothing is copied and
no file is edited by hand.

**ffmpeg is handled for you.** The `.zip` download ships it in `ffmpeg/`
beside the .exe, so there is nothing to install. If you took the bare .exe
instead, it fetches its own copy into `ffmpeg/` on the first run -- about
110MB, once, with a progress bar. An ffmpeg already on PATH is used as-is and
nothing is downloaded. `--no-download` turns the fetch off if you would rather
install it yourself.

Drop your own clips in `footage/` beside the .exe if you use the upload source.
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
python -m agent.main
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

## Building the .exe

```bash
python agent/build_exe.py --clean
```

Around 25MB, and it lands at `agent/ClipForgeAgent.exe`. To build the file
subscribers actually download -- the .exe and ffmpeg together in one archive:

```bash
python agent/build_exe.py --clean --bundle
```

That produces `agent/ClipForgeAgent-windows.zip`, about 100MB. It needs
`agent/ffmpeg/` to exist first; run the agent once and let it fetch one.

ffmpeg sits *next to* the .exe rather than inside it. Two static binaries are
about 200MB, and PyInstaller's onefile mode unpacks its entire payload into a
temp directory on every launch -- burying them would write 200MB to disk each
time a long-running agent starts. The .zip gets the same one-download install
without paying that on every run.

The build is GPL, because the pipeline encodes with `libx264` and an LGPL
ffmpeg has no software H.264 encoder at all. That means the .zip must keep
ffmpeg's `LICENSE` alongside the binaries and point at the source, which
`READ ME FIRST.txt` does. The binaries are unmodified upstream builds from
gyan.dev and the agent invokes them as a separate process, so nothing here
makes ClipForge itself a derived work.

The server half of the repo is excluded from the build, so SQLAlchemy, FastAPI,
Stripe and the Google client are not along for the ride. The .exe is gitignored
because it is a build artefact; the spec and this script are what is kept.

## Where the .exe comes from

Set `AGENT_DOWNLOAD_URL` on the server to wherever the build is published -- a
GitHub release, normally -- and the app shows a download button next to the
pairing instructions. Left unset, it shows the run-from-source route instead of
a button that leads nowhere.

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
