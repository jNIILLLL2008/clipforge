<!-- Design system for the ClipForge marketing page (frontend/landing.html +
frontend/landing.css). Read this before changing the landing page.

This replaces the previous contents of this file, which were a vendored analysis
of linear.app taken from github.com/VoltAgent/awesome-design-md. That document
described someone else's brand, and the page built from it read as a Linear
clone: the same near-black canvas and the same #5e6ad2 lavender. The old file is
still in git history if you want it back.

The app (frontend/index.html + styles.css) now shares this palette, type and
radius scale, so the two surfaces read as one product. See "The app" at the
bottom for the one place they deliberately differ. -->

---
version: 1
name: ClipForge-marketing
description: "An instrument, not a brochure. The product's whole story is that it refuses: it refuses unlicensed footage per clip, and it refuses to render a video that scores below the retention bar. The page is built like a measuring device. Near-black neutral canvas, bone ink, one ember accent reserved for the parts that are actually running, and every number set in mono. Dark is the brand default and light is a first-class alternative driven by the same tokens."

dials:
  design_variance: 7      # asymmetric grids, no centred hero
  motion_intensity: 5     # entry reveal and hover feedback, nothing looping
  visual_density: 4       # standard marketing spacing

colors:
  # The single chromatic accent. Nothing else on the page is coloured.
  ember: "#e2603a"        # fills: primary CTA, brand mark, CSS check marks
  ember-ink: "#ff8a63"    # dark-mode text variant, 7.3:1 on canvas
  ember-ink-light: "#b8431f"  # light-mode text variant
  on-ember: "#12100e"     # label on an ember fill, 5.4:1, same in both themes

  dark:
    canvas: "#0b0b0d"
    surface: "#131316"
    surface-2: "#191920"
    surface-sunk: "#08080a"
    hairline: "#25252c"
    hairline-firm: "#34343d"
    ink: "#f4f2ef"
    ink-muted: "#b7b4ae"
    ink-subtle: "#8a8781"

  light:
    canvas: "#f5f5f4"
    surface: "#ffffff"
    surface-2: "#fafaf9"
    surface-sunk: "#ececeb"
    hairline: "#e3e3e0"
    hairline-firm: "#c9c9c5"
    ink: "#141416"
    ink-muted: "#4c4c50"
    ink-subtle: "#6d6d71"

typography:
  sans: Geist            # via Google Fonts, weights 400/500/600
  mono: Geist Mono       # weights 400/500, used for numbers only
  display-xl: "clamp(38px, 4.4vw, 56px), line-height 1.06, tracking -.035em"
  display-lg: "clamp(32px, 3.9vw, 46px), line-height 1.10, tracking -.030em"
  display-md: "clamp(26px, 2.9vw, 34px), line-height 1.15, tracking -.025em"
  headline:   "clamp(21px, 2.1vw, 26px), line-height 1.25, tracking -.020em"
  body: "16px / 1.55"

radius:
  # One documented system. Do not introduce a fourth value.
  chip: 2px      # tags, verdict pills
  control: 4px   # buttons, inputs
  panel: 8px     # cards, stills, the CTA band
---

## The rules this page is held to

**One accent, everywhere.** `--ember` is the only chromatic colour on the page.
If a new section needs to signal something, it uses ink weight or a hairline,
not a second hue. There is no green success state and no red error state in the
marketing page.

**The primary button is theme-independent.** Ember fill, `--on-ember` label,
5.4:1 in both light and dark. It does not change colour between modes, so the
primary action keeps one identity. Never put white text on the ember fill; it
lands around 3.4:1 and fails AA.

**Numbers are mono, prose is sans.** Scores, weights, prices and clip counts use
Geist Mono with tabular figures. Nothing else does.

**Zero em-dashes.** Not in headlines, body, captions, alt text or button labels.
Use a comma, a colon, a full stop, or restructure the sentence. This is a hard
rule and the page currently has none.

**Eyebrows are rationed to one per three sections.** Right now the page has
seven sections and exactly two eyebrows, on the retention gate and the footage
section. Every other section leads with its headline. Do not add an eyebrow to
a section just because it looks bare.

**No fake product UI.** The hero previously contained a Studio screenshot built
out of `<div>` rectangles. It is gone and it does not come back. If the page
needs to show the product, use a real screenshot. Until one exists, the hero
carries real vertical footage frames, which is what the product actually makes.

**No step numbers and no section numbering.** "01 / 02 / 03" above the three
setup steps was removed. The verb is the label.

**Layout families do not repeat.** Across the page: asymmetric hero split,
hairline-separated step columns, a numeric-focal gate split, a three-cell bento,
a pricing card grid, an accordion, a full-width band. If you add a section, it
gets a family that is not already in that list.

## Layout notes worth keeping

`.hero-copy` deliberately has no `max-width` in `ch`. A `ch` unit resolves
against the element's own font size, and on a 16px wrapper `34ch` collapsed the
column to roughly 272px, which pushed the 56px headline to four lines. The grid
column governs the hero width; the lede carries its own `46ch` measure at its
own font size.

The bento has exactly three cells for three pieces of content: a `.cell-wide`
(2 columns) and a normal cell fill the first row, and a `.cell-full`
(`grid-column: 1 / -1`) closes the second. Three cells cannot fill a two-column
grid without leaving a hole, so the bento drops straight from three columns to
one at 1000px. If you change the cell count, re-check that at every breakpoint,
and never leave an empty tile to balance a row.

## Motion

`MOTION_INTENSITY 5`. One effect: a translate-and-fade reveal as elements enter
the viewport, driven by `IntersectionObserver`. Never a scroll listener.

The reveal starts at `opacity: 0`, so anything that stops the observer from
delivering would leave the page blank rather than merely unanimated. There is a
`load` plus 900ms safety net in `landing.html` that reveals everything if
nothing has been revealed by then. Keep it. The whole reveal layer is also gated
behind a `.js` class on `<html>`, so the page is fully readable with JavaScript
off, and it collapses to static under `prefers-reduced-motion`.

## Third-party assets, and what to replace

The page has no build step. It is plain HTML and CSS served by FastAPI from
`frontend/`, so there is no bundler to install an icon family or self-host fonts
into. Three consequences, each a deliberate trade:

* **Fonts** load from Google Fonts via `<link>` with `preconnect`. Self-hosting
  would be faster and is the right move if a build step ever appears.
* **Check marks** in the pricing tiers are drawn with CSS borders rather than
  icon SVGs, because there is no package to install one from.
* **Logos** in the sources strip come from the Simple Icons CDN. The two-colour
  URL form (`/{slug}/{light}/{dark}`) bakes a `prefers-color-scheme` query into
  the SVG, so one request per logo covers both themes.

**Hero stills are real renders.** `frontend/img/hero-frame-{1,2,3}.jpg` are
actual published outputs, showing the format the pipeline produces: banner,
numbered list, burned-in captions. Roughly 265x480 each, about 104KB for all
three. If you swap them, keep the explicit `width`/`height` attributes so
nothing shifts while they load, keep `fetchpriority="high"` on the centre still
(it is the LCP element), and keep `loading="lazy"` off the two side stills,
which sit above the fold.

One caveat worth knowing: those frames are CBS Sports and Paramount+ broadcast
content. That is third-party copyrighted material sitting on a commercial
marketing page, and it sits a little awkwardly next to the "what this does not
do" section, which is about exactly this. Own footage or a licensed-stock render
would carry the same message without the tension.

**Still a placeholder:** the wide footage cell in the bento uses
`picsum.photos`, marked `TODO` in the markup. It wants a still of footage the
user shot themselves, so none of the CBS frames fit it.

## Footage sources

The bot is upload-only. The stock and open-collection adapters (Pexels,
Pixabay, Openverse, the Internet Archive) were removed from the registry, so
the marketing page must not advertise them. If sources are ever added back,
the copy that has to change with them is: the hero lede, the logo strip under
the hero, the "Upload your footage" step, the whole `#footage` section, and the
first two FAQ answers. The YouTube adapter is still present and still ships
disabled behind two opt-ins.

## Things the page must not disagree with

Pricing is fetched from `/api/plans` on load and overwrites the printed values,
so the page cannot contradict Stripe. The printed numbers are the fallback for
when the API is unreachable. A plan whose price carries no unit, such as the
free plan returning `"Free"`, must clear the `/ month` suffix rather than render
"Free / month".

Anchor IDs `#how`, `#retention`, `#footage` and `#pricing`, the `/app` links and
the `?plan=` query parameters are load-bearing. Do not rename them.

## The app

`frontend/styles.css` reads its palette, type and radius scale from the same
values documented above, so the Studio and the marketing page look like one
product. Its structure was left alone; only the theme was remapped.

The one deliberate divergence is semantic colour. The marketing page has a
single accent and no state colours at all. A product UI has to signal success
and failure, so the app keeps `--good`, `--warn` and `--bad`. They are
desaturated to sit beside ember rather than shout over it:

| token | value | why |
|---|---|---|
| `--good` | `#57b071` | 5.45:1 on its own pill wash, 7.35:1 on canvas |
| `--warn` | `#d9a92e` | 6.44:1 on its pill wash |
| `--bad`  | `#ff5c72` | a rose red, 22 degrees off ember's hue, 5.03:1 on its pill wash |

`--bad` is the one to be careful with. An error colour close to an orange accent
is easy to confuse, so it is pushed toward rose rather than the obvious
`#ff453a`. If you retune the accent, re-check that separation.

Two accent variants exist for the same reason as on the marketing page:
`--accent` for fills, `--accent-ink` (`#ff8a63`) wherever the accent is used as
text. `--accent-text` (`#12100e`) is the label on an ember fill. Never white.
