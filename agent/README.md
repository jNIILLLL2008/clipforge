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

Either run it from source, or use the packaged `.exe` and skip installing
Python. **ffmpeg has to be on PATH either way** -- check with `ffmpeg -version`,
and install it with `winget install Gyan.FFmpeg` if it is missing.

### From the .exe

Three things in one folder, and nothing else:

```
ClipForgeAgent.exe
agent.env         copied from agent.env.example, with your token
footage/          your own clips
```

Then `ClipForgeAgent.exe --check`. The .exe reads everything from the folder it
sits in, so keep those three together if you move it.

### From source

You need Python 3.11+.

1. On the website, sign in and open **Settings**, then pair a render agent.
   The token is shown once. Copy it.
2. Copy `agent.env.example` to `agent.env` and fill in the server and token.
3. Put your own clips in `footage/`.
4. Check everything before running for real:

```bash
python -m agent.main --check
```

That verifies the token, reports your plan and remaining runs, confirms ffmpeg,
and counts the footage it can see. Then:

```bash
python -m agent.main
```

It polls until you stop it. `--once` takes a single job and exits, which is
what you want from a scheduled task.

## Settings

Everything lives in `agent.env`. Only the first two are required.

| Setting | Default | |
| --- | --- | --- |
| `CLIPFORGE_SERVER` | | The site you subscribed to |
| `CLIPFORGE_AGENT_TOKEN` | | From Settings, shown once |
| `CLIPFORGE_FOOTAGE_DIR` | `./footage` | Your own clips |
| `CLIPFORGE_WORK_DIR` | `./work` | Scratch space, cleaned as it goes |
| `CLIPFORGE_POLL_SECONDS` | `5` | Wait after finishing a job |
| `CLIPFORGE_IDLE_SECONDS` | `20` | Wait when there was nothing to do |

`agent.env`, `footage/` and `work/` are all gitignored. The token is a
credential: anything holding it can claim your jobs. Revoking it on the website
stops it immediately.

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
