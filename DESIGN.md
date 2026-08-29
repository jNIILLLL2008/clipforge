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
  design_variance: 6      # centred hero, asymmetric grids below it
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
  # One documented system, softened to match the reference design. Do not
  # introduce a fourth value.
  chip: 999px    # tags, verdict pills, the hero badge
  control: 12px  # buttons, inputs
  panel: 16px    # cards, stills, the framed hero panel, the CTA band
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
out of `<div>` rectangles. It is gone and it does not come back. What sits in
the framed panel is three real renders, which is what the product actually
makes. The frame is the reference design's; the contents are not a stock app
screenshot and must not become one.

**No borrowed customers.** The reference this design comes from puts a wall of
Nvidia, GitHub, Nike and OpenAI logos under the hero. Those are not ClipForge
customers and the strip below the hero names the one service the product
actually talks to instead. If that ever becomes a logo wall, it has to be
companies who really use this.

**No step numbers and no section numbering.** "01 / 02 / 03" above the three
setup steps was removed. The verb is the label.

**Layout families do not repeat.** Across the page: centred hero over a framed
panel, hairline-separated step columns, a numeric-focal gate split, a three-cell
bento, a pricing card grid, an accordion, a full-width band. If you add a
section, it gets a family that is not already in that list. The hero is the one
centred thing on the page; everything below it stays asymmetric, which is what
keeps the centring from reading as a default rather than a choice.

## The hero, and where it comes from

The hero follows a reference design: centred, opening on a pill badge, then the
headline, then a framed product panel, over a raked radial glow. Three details
are load-bearing.

**The glow** is two long ellipses rotated 45 degrees out of the top left, with
a `radial-gradient(125% 125% at 50% 100%)` vignette over the top pulling the
canvas back up from the bottom. Without the vignette the glow has no edge to
end on and the section just looks unevenly lit.

**The badge arrow** is two copies of the same glyph in a track twice the
visible width, with `overflow: hidden` on the parent. Hover slides the track
one arrow-width, so the first appears to leave and a second to follow it in. It
is one transform, not an animation loop.

**The nav** contracts into a glass pill once the page has moved, driven by an
IntersectionObserver on a 64px sentinel at the top of the document. Not a
scroll listener. The sentinel has height on purpose: pinned at `y=0` with no
height it would flicker on the first pixel of scroll, and a negative
`rootMargin` on the observer pushes the observed area past the sentinel
entirely, so the bar comes up already contracted.

## Layout notes worth keeping

Measure limits in the hero go on the elements that set the type size, never on
a wrapper. A `ch` unit resolves against the element's own font size, so `34ch`
on a 16px wrapper once collapsed the column to roughly 272px and pushed the
56px headline to four lines. `.hero .display-xl` carries `18ch` at its own size
and `.lede` carries `52ch` at its own.

The bento has exactly three cells for three pieces of content: a `.cell-wide`
(2 columns) and a normal cell fill the first row, and a `.cell-full`
(`grid-column: 1 / -1`) closes the second. Three cells cannot fill a two-column
grid without leaving a hole, so the bento drops straight from three columns to
one at 1000px. If you change the cell count, re-check that at every breakpoint,
and never leave an empty tile to balance a row.

## Motion

`MOTION_INTENSITY 5`. Two effects, both entrances, both lift-and-unblur.

`.rise` is the hero sequence: a CSS animation with staggered delays, so the
badge, headline, subtext, buttons and panel arrive in reading order. It is an
animation rather than a transition because it fires on load with nothing to
observe. The blur is what makes text appear to resolve rather than simply fade
in, and it is the single thing that most carries the reference's feel.

`.reveal` is the same idea below the fold, fired as sections arrive, driven by
`IntersectionObserver`. Never a scroll listener.

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

## The sign-in screen

Also ported from a reference design, and the same trade as the hero: the
original renders a dot field as a WebGL fragment shader through three.js and
`@react-three/fiber`. Pulling a 3D engine and a renderer into a buildless
frontend to fade in a grid of squares is not a trade worth making, so
`startGateDots()` in `app.js` draws the same field on a 2D canvas. The per-cell
hash, the distance-based delay and the flicker are ported from the shader; the
dependency is not.

Three things about it are deliberate:

* **It stops.** The loop ends when the gate is hidden, watched with a
  MutationObserver on the class, and when the tab goes to the background. A
  requestAnimationFrame loop running behind a signed-in app is pure battery.
* **Reduced motion gets a settled frame**, and that frame skips the flicker
  term rather than inheriting whatever phase the sine happened to be at when it
  was drawn.
* **The form sits on the field, not on a card.** That is what makes the dots
  read as the page rather than as a picture hung behind one. The two washes
  over the top, a radial one opening a dark hole in the middle and a linear one
  settling the top edge, are what keep the text legible on it.

The submit button holds its label in a `.label` span. `app.js` rewrites that
span, never the button, because the button also contains the arrow that slides
on hover and `textContent` on the parent deletes it.

## The app

`frontend/styles.css` reads its palette, type and radius scale from the same
values documented above, so the Studio and the marketing page look like one
product. Its structure was left alone; only the theme was remapped. It also
carries the same raked glow behind the app shell and the same saturated glass
on the tab bar, so signing in does not feel like arriving somewhere else.

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
