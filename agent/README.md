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

**ffmpeg has to be on PATH** -- `ffmpeg -version` to check, `winget install
Gyan.FFmpeg` on Windows if it is missing. The agent says so plainly rather than
failing halfway through a render.

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

Around 24MB, and it lands at `agent/ClipForgeAgent.exe`. ffmpeg is left out on
purpose: it is roughly 90MB, it is better installed and updated by the person
using it, and `--check` reports clearly when it is missing.

The server half of the repo is excluded from the build, so SQLAlchemy, FastAPI,
Stripe and the Google client are not along for the ride. The .exe is gitignored
because it is a build artefact; the spec and this script are what is kept.

## Where the .exe comes from

Set `AGENT_DOWNLOAD_URL` on the server to wherever the build is published -- a
GitHub release, normally -- and the app shows a download button next to the
pairing instructions. Left unset, it shows the run-from-source route instead of
a button that leads nowhere.

## Serving jobs from the server side

For an instance to leave its jobs to agents rather than rendering them itself:

```bash
RENDER_WORKERS=0
```

Jobs then queue and wait. They do not fail while the agent is offline, so a
machine that is asleep at 9am picks the run up when it wakes.

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
