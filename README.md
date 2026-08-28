# ClipForge

A subscription web app that builds short-form videos: the user picks a niche,
the service sources footage that is licensed for reuse, cuts it to a
retention-tested format, and hands back an MP4.

Built alongside — and entirely separate from — the single-channel tool in
`../YOUTUBE`, which is untouched.

```
backend/app/
  main.py          FastAPI app, serves the API and the SPA
  config.py        every setting, read from .env
  models.py        users, plans, niches, jobs, clips
  niches.py        the built-in niches and forking
  auth.py          signup/login, PBKDF2 + signed tokens
  worker.py        background render queue
  routes/
    api.py         accounts, niches, uploads, jobs
    billing.py     Stripe checkout, portal, webhook
  sources/         where footage comes from (see below)
  render/
    pipeline.py    one job end to end
    retention.py   the quality gate
    overlay.py     banner, checklist and captions as one ASS layer
    engine.py      ffmpeg concat + burn-in, single pass
frontend/          index.html, app.js, styles.css (no build step)
```

## Running it

Needs Python 3.11+ and ffmpeg on PATH.

```bash
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then:

```bash
.venv\Scripts\python -m uvicorn backend.app.main:app --reload
```

Open <http://localhost:8000>. It boots with no API keys — uploads work
immediately, and the other sources switch on as you add keys.

Check everything still works, offline and without keys:

```bash
.venv\Scripts\python selftest.py
```

## The two promises, and how they are kept

### "No copyright issues"

This is enforced in code, not in a policy page.

* Every adapter declares a `reusable` flag and every clip carries its licence.
* `sources/__init__.py` refuses to hand a job any adapter that is not cleared
  for commercial reuse, unless an operator sets `ALLOW_UNLICENSED_SOURCES`.
* The pipeline re-checks the flag **per clip**, so a source that returns mixed
  licences cannot slip one through.
* Clips needing credit are recorded with `attribution_required`, and the
  credit line is generated for the description.

Shipped source: the user's own uploads. The stock and open-collection
adapters (Pexels, Pixabay, Openverse, archive.org) were removed, because they
hold no broadcast, sport or gaming footage and that is what this is used for.
The licence machinery above still stands and still gates the YouTube adapter.

**The honest limit.** This means no broadcast footage. A niche built on
someone else's TV show cannot be made claim-free by any amount of engineering,
because Content ID matches the content itself regardless of who uploaded it.
Those niches are possible here only through the **upload** source, where the
user supplies material they have the rights to.

### The YouTube source

There is a working YouTube adapter (`sources/youtube_source.py`). It finds
clips from channels, channel *archive searches* (which reach material a
channel's recent tab does not, and matter for a seasonal show), and hashtag
Shorts tabs; downloads with yt-dlp; and pulls auto-captions, which feed both
the burned-in subtitles and the music scan.

It declares `reusable = False`, so switching it on takes two deliberate steps:
add `youtube` to `ENABLED_SOURCES` **and** set `ALLOW_UNLICENSED_SOURCES=true`.
Doing one without the other leaves it blocked, and the Activity screen shows it
as **blocked** rather than ready.

That is not squeamishness about capability — it is where the trade-off sits.
Downloading breaks YouTube's Terms of Service, Content ID matches the content
whoever re-uploaded it, and on a paid service the liability is the operator's
rather than the subscriber's. Competing tools make the same trade; the
difference here is that it is a switch you throw knowingly rather than a
default you inherit.

### "No videos with no retention"

`render/retention.py` scores every video **before** it is encoded, out of 100:

| Weight | Rule |
|--:|---|
| 25 | The opening clip reaches the action inside the niche's hook window |
| 20 | No single shot runs past the niche's limit |
| 20 | Cuts per minute land in a watchable band (~8–30) |
| 20 | Something promises a payoff: countdown, numbered list, or fast cutting |
| 10 | Captions, because most short-form is watched muted |
|  5 | Total length is sane for the format |

Below 55 the job is **rejected before rendering**, the reasons are shown, and
the render is refunded to the user's monthly allowance. Between 55 and 72 it
renders but reports what is weak.

## Pages

| Route | Serves |
|---|---|
| `/` | `frontend/landing.html` — the marketing page |
| `/app` | `frontend/index.html` — the studio, which shows its own sign-in |

The landing page follows `DESIGN.md` in the repo root, taken from
[VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md)
(the linear.app system): a near-black `#010102` canvas, a four-step surface
ladder carrying hierarchy instead of shadows, hairline borders, and the lavender
`#5e6ad2` accent used **only** on the brand mark, the primary CTA and focus
rings. Inter substitutes for Linear's proprietary display face, as that spec
recommends. No gradients, no second accent, no pill-rounded CTAs.

The hero's product shot is built in markup rather than screenshotted, so it
stays sharp at any size and cannot go stale when the app's UI changes.

Read `DESIGN.md` before changing the landing page. The app itself uses its own
product palette in `frontend/styles.css` and is not bound by it.

## How it works for a subscriber

On a phone the four screens sit behind a bottom tab bar. From 900px up the tab
bar becomes a **sidebar**, Home splits into two columns (the pipeline on the
left, automation and overview beside it), and Settings lays its groups out in
two columns — three above 1400px — instead of one long scroll.

A **first-run tour** opens the first time someone signs in: five steps covering
what the tool does, loading a preset, where footage comes from, connecting a
channel, and why a video can be rejected. It is skippable, reachable again from
the bottom of the sidebar, and the "seen" flag lives on the account rather than
in the browser, so it does not reappear on a second device.

Accessibility: the nav is a real tablist with roving tabindex and arrow-key
movement, every control has a label, status changes are announced through live
regions, the tour traps focus and closes on Escape, there is a skip link, focus
is always visible, and animation respects `prefers-reduced-motion`.

The four screens:

- **Home** — a Publish button, a Dry run button, a status panel that says what
  would stop a run, the daily automation switch, and an overview of the current
  configuration. One press does everything: source, cut, score, render, upload.
- **Settings** — one flat list of grouped rows holding every option (below).
- **History** — past runs, their retention score, and links to YouTube.
- **Activity** — your uploaded footage, which sources are available, your plan.

There is **one configuration per account**, not a library of them. Presets load
a starting point over it; the Settings screen is where it actually lives. This
is deliberate — the product's promise is one button, and that only works if
there is no "which one?" question in front of it.

### Publishing

Connect a channel once on the Home screen. Renders then upload automatically
unless **Publish after rendering** is off. Visibility defaults to **private**,
because the first thing anyone should do is watch what it made.

Publishing needs a Google OAuth client (see `.env.example`). Without one the
app runs fine and videos are download-only, which is also how the test suite
runs.

### Daily automation

Paid plans get **Run every day** with a time and timezone. A scheduler thread
checks every minute and queues a run when an account's local time arrives. Two
guards: an account runs at most once per calendar day in its own timezone, and
the plan is re-checked at fire time, so a lapsed subscription stops publishing.
A window missed by more than two hours is skipped rather than fired late.

## Niches

Seven built-ins ship: Top 5 Countdown, Funny Moments, Meme Cuts, Oddly
Satisfying, Did You Know, Quick How-To, and One TV Show. They differ by
*shape* — pacing, clip count, whether a numbered list is shown — because shape
drives retention; topic is just search terms.

Users fork a built-in (or start blank) to get an editable copy. How many they
can keep is a plan limit.

### Settings

A niche carries **62 settings in 11 groups** — the full option set from the
desktop tool, minus what belongs to the operator (API keys, storage,
publishing credentials) and plus this product's retention rules.

| Group | What it controls |
|---|---|
| Subject | Description for the AI, search terms, exclusions, sources, channels, archive searches, pool size |
| Show filter | Restrict to one programme: show name, keywords, regulars |
| Clip filters | Duration, views, age, blocked and trusted channels, long-segment threshold |
| The cut | Clip count, total length, segment bounds, trim strategy, countdown order |
| Retention rules | Hook window and longest unbroken shot |
| Banner | Text with `{count}`, font, size, two colours |
| Numbered list | Font, size, position |
| Captions | Font, size, colour, height, words per line, capitals |
| Countdown badge | Corner badge, size, position, label |
| Video | Resolution, fps, fit mode, blur, CRF, preset, audio bitrate, loudness |
| Copyright guard | Music scan, rejection threshold, clearance |
| Upload | Publish after render, visibility, category, made-for-kids, schedule delay, title suffix |

They are declared once in `settings_schema.py`, which generates the defaults,
the API validation and the editor UI — so a new option is added in one place
and cannot drift between them. `sanitise()` drops unknown keys and forces every
value into range, so a niche can never hold something the renderer would choke
on.

**The show filter** is what makes a niche like "one specific TV panel show"
possible. A clip qualifies on an explicit show keyword, or on naming two or
more of the show's regulars together. Aliases are grouped per person with `|`
(`thierry henry|thierry|henry`) so one person's name is never miscounted as
two different regulars — without that, a clip about him alone passes a filter
meant to catch panel moments.

## Plans

| | Free | Starter | Pro |
|---|---|---|---|
| Renders / month | 3 | 40 | 300 |
| Max clips | 5 | 8 | 12 |
| Max length | 60s | 180s | 300s |
| Daily automation | no | yes | yes |
| Watermark | yes | no | no |

Renders are **reserved when a job is queued**, not when it completes —
otherwise a user could queue a month's work before the first one finished.
Failed and rejected jobs refund the reservation.

### How customers actually pay

Billing is Stripe Checkout plus Stripe's hosted customer portal, so **no card
details ever touch this server** — that is what keeps you out of PCI scope.

The flow:

1. A subscriber presses upgrade on the Activity screen.
2. `POST /api/billing/checkout?plan=starter` creates (or reuses) a Stripe
   Customer and returns a Checkout Session URL.
3. They pay on Stripe's own page.
4. Stripe calls `POST /api/billing/webhook`. **That is the only place a plan is
   ever changed** — a user returning to the success URL proves nothing, whereas
   a signed webhook does.
5. The webhook sets their plan, resets their monthly allowance, and daily
   automation unlocks.

Cancellations and card changes go through the portal (`POST
/api/billing/portal`), and `customer.subscription.deleted` drops them back to
Free.

**Until you configure Stripe, nobody can pay.** The app runs fine — everyone
sits on the Free plan and the pricing rows show the price with no upgrade
button plus a note saying payments are not switched on.

To switch it on:

1. Create a Stripe account and take the secret key from the dashboard
   (`sk_test_…` while you are testing).
2. Create two **recurring monthly** Products/Prices — Starter and Pro — and
   copy their price IDs (`price_…`, not the product ID).
3. Add a webhook endpoint pointing at
   `https://yourdomain/api/billing/webhook`, subscribed to
   `customer.subscription.created`, `.updated` and `.deleted`, then copy its
   signing secret (`whsec_…`).
4. Fill in `STRIPE_SECRET_KEY`, `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO` and
   `STRIPE_WEBHOOK_SECRET`, and set `PUBLIC_URL` to your real domain so the
   redirect back from Checkout works.
5. Set `PRICE_LABEL_STARTER` / `PRICE_LABEL_PRO` to match what the Stripe
   Prices actually charge, including the currency. These are display strings
   only, so if they drift a customer sees one number and is charged another.

Test with Stripe's test-mode card `4242 4242 4242 4242`, any future expiry.
Webhooks cannot reach `localhost`, so use `stripe listen --forward-to
localhost:8000/api/billing/webhook` while developing.

## Deploying

This is **not** a static site and cannot go on Vercel, Netlify or GitHub Pages.
It needs ffmpeg, background threads that run for minutes, and a disk that
survives a restart. Anything that runs a container with a persistent volume
works: a VPS, Railway, Render, Fly.io, Hetzner.

Check first — it catches the silent problems, not just crashes:

```bash
.venv\Scripts\python check_deploy.py
.venv\Scripts\python check_stripe.py
```

### The quickest route: any VPS with Docker

```bash
git clone <your repo> && cd clipforge
cp .env.example .env      # then fill it in
docker compose up -d --build
```

That starts the app on port 8000 plus Postgres, with named volumes for the
database and the media. Put Caddy or nginx in front for TLS — `PUBLIC_URL` must
be `https://`, or session cookies and OAuth tokens travel in clear text.

### What must change from your local `.env`

| Setting | Local | Live |
|---|---|---|
| `ENV` | development | `production` |
| `DEBUG` | true | `false` |
| `SECRET_KEY` | anything | a real random value — see below |
| `PUBLIC_URL` | localhost:8000 | `https://yourdomain.com` |
| `DATABASE_URL` | SQLite | `postgresql+psycopg://…` |
| `GOOGLE_REDIRECT_URI` | localhost | `https://yourdomain.com/api/youtube/callback` |
| Stripe keys | `sk_test_…` | `sk_live_…` and live price IDs |

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The app **refuses to boot** in production with a development `SECRET_KEY`,
`DEBUG` on, or no Stripe key, rather than starting up quietly broken.

### After you switch the domain over

1. Add a Stripe webhook at `https://yourdomain.com/api/billing/webhook` and put
   its `whsec_…` in `.env`. The `stripe listen` secret only works locally.
2. Add the same domain's callback URL to the OAuth client in Google Cloud, or
   connecting a channel fails with `redirect_uri_mismatch`.
3. Re-run both checkers against the live config.

### Scaling past one box

The render queue and the daily scheduler both live **inside the web process**.
That is deliberate and fine for one instance, but if you run several:

- exactly one gets `RUN_SCHEDULER=true`; the rest get `false`, or some accounts
  publish twice a day;
- renders are written to local disk, so either share a volume or move to object
  storage, otherwise a download hits the wrong instance and 404s.

## Before going live

- [ ] `SECRET_KEY` set, `ENV=production`, `DEBUG=false` (startup refuses otherwise)
- [ ] Postgres in `DATABASE_URL`; SQLite will not survive concurrent workers
- [ ] A real migration tool (Alembic). Startup adds missing columns
      automatically, which covers the additive changes that make up nearly
      every schema change here, but it will not rename, retype or drop
      anything — and it is not a substitute for versioned migrations once
      there is data you cannot lose
- [ ] Object storage for `storage/` — renders are on local disk today
- [ ] Stripe webhook pointed at `/api/billing/webhook`
- [ ] Rate limiting in front of `/api/auth/*`
- [ ] Email verification and password reset (neither exists yet)
- [ ] A retention policy for renders; nothing is cleaned up automatically
- [ ] **Apply for a YouTube quota increase.** The default 10,000 units/day
      allows about 6 uploads across all users combined — nowhere near enough
      for paying subscribers on daily automation.
- [ ] Google OAuth verification, needed before non-test users can connect a
      channel without a warning screen
