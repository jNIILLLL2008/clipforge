/* consent.js -- The cookie notice, and the gate the trackers sit behind.

   The point of this file is the gate, not the banner. A banner that appears
   after the tracker has already loaded is worse than no banner: it records a
   choice the site did not honour. So nothing optional is allowed to load by
   any other route -- there is no analytics snippet in the HTML, and the only
   thing that can start one is `grant()` below.

   What that means in practice:

     * Strictly necessary storage runs regardless and is not asked about. That
       is the `cf_token` session cookie, and consent is not the lawful basis
       for it -- you cannot sign in without it, and asking implies a choice
       that does not exist.
     * Everything else is declared in `OPTIONAL` on the script tag. If that
       list is empty there is nothing to consent to, so no banner is shown.
       Adding an analytics id is what makes the banner appear, which is the
       right way round: the notice follows the trackers rather than the other
       way about.

   The stored answer is in localStorage rather than a cookie, because a cookie
   recording that you declined cookies is a joke that regulators have heard.  */
(function () {
  "use strict";

  var KEY = "cf_consent";
  /* Bump when the optional list changes materially. An old answer covers only
     the things it was asked about. */
  var VERSION = 1;
  /* Consent is not forever. Twelve months is the window supervisory
     authorities in the EU generally expect a fresh ask after. */
  var MAX_AGE_DAYS = 365;

  var script = document.currentScript;
  /* Rendered from config server-side: a comma-separated list of the optional
     things this deployment actually uses. Empty in a default install. */
  var optional = ((script && script.getAttribute("data-optional")) || "")
    .split(",").map(function (s) { return s.trim(); }).filter(Boolean);
  var gaId = (script && script.getAttribute("data-ga")) || "";

  var pending = [];
  var state = read();

  /* ------------------------------------------------------------ storage -- */

  function read() {
    /* Private-mode browsers and blocked site data both throw here rather than
       returning null, and a policy page that crashes is not a good look. */
    try {
      var raw = window.localStorage.getItem(KEY);
      if (!raw) return null;
      var saved = JSON.parse(raw);
      if (!saved || saved.v !== VERSION) return null;
      var age = (Date.now() - (saved.t || 0)) / 86400000;
      if (age > MAX_AGE_DAYS || age < 0) return null;
      return saved;
    } catch (e) {
      return null;
    }
  }

  function write(answer) {
    state = { v: VERSION, t: Date.now(), analytics: !!answer };
    try {
      window.localStorage.setItem(KEY, JSON.stringify(state));
    } catch (e) {
      /* Storage unavailable. The answer still holds for this page view, it
         just cannot be remembered -- so the notice comes back next time,
         which is the safe direction to fail in. */
    }
  }

  /* -------------------------------------------------------------- gate -- */

  function granted() { return !!(state && state.analytics); }

  /* Run `fn` once analytics is allowed, now or later. Anything that sets a
     non-essential cookie belongs in here and nowhere else. */
  function onGrant(fn) {
    if (typeof fn !== "function") return;
    if (granted()) { fn(); return; }
    pending.push(fn);
  }

  function release() {
    var queued = pending;
    pending = [];
    queued.forEach(function (fn) {
      try { fn(); } catch (e) { /* one bad handler must not block the rest */ }
    });
  }

  /* The one optional tracker this build knows how to start. It is here rather
     than in the page so there is exactly one code path that can load it, and
     that path is behind the gate. */
  function startAnalytics() {
    if (!gaId || window.__cfGaStarted) return;
    window.__cfGaStarted = true;

    var tag = document.createElement("script");
    tag.async = true;
    tag.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(gaId);
    document.head.appendChild(tag);

    window.dataLayer = window.dataLayer || [];
    function gtag() { window.dataLayer.push(arguments); }
    window.gtag = gtag;
    gtag("js", new Date());
    /* No cross-site advertising signals, and the last octet of the address
       dropped before it is stored. Neither is a substitute for the consent
       above; both reduce what is collected once it is given. */
    gtag("config", gaId, { anonymize_ip: true, allow_google_signals: false });
  }

  /* -------------------------------------------------------------- view -- */

  function build() {
    var el = document.createElement("aside");
    el.className = "cc";
    el.id = "cookie-notice";
    el.setAttribute("role", "region");
    el.setAttribute("aria-label", "Cookie choices");
    el.innerHTML =
      '<p class="cc-title"><span class="brand-mark" aria-hidden="true">&#9670;</span> Cookies</p>' +
      '<p>Signing in needs one cookie, so that one is always on. Beyond it we ' +
      'would like to measure which pages get used, which you can decline with ' +
      'no loss of function. <a href="/cookies">What we store</a>.</p>' +
      '<div class="cc-actions">' +
        '<button type="button" class="cc-btn cc-accept" data-cc="yes">Accept analytics</button>' +
        '<button type="button" class="cc-btn cc-reject" data-cc="no">Essential only</button>' +
      '</div>';

    el.addEventListener("click", function (event) {
      var choice = event.target.getAttribute && event.target.getAttribute("data-cc");
      if (!choice) return;
      decide(choice === "yes");
    });

    return el;
  }

  var node = null;

  function show() {
    if (node) { node.hidden = false; return; }
    node = build();
    document.body.appendChild(node);
  }

  function hide() { if (node) node.hidden = true; }

  function decide(yes) {
    write(yes);
    hide();
    if (yes) { startAnalytics(); release(); }
    /* A refusal clears the queue rather than holding it: a handler kept
       waiting for an answer already given would fire on a later grant that
       the visitor did not make on this page. */
    else { pending = []; }
  }

  /* ------------------------------------------------------------- start -- */

  /* Nothing optional in this deployment: no banner, and nothing to gate.
     The public API stays in place so a page can still call it safely. */
  if (optional.length) {
    if (granted()) {
      startAnalytics();
    } else if (!state) {
      /* No answer on file. Ask, once the page has something to attach to. */
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", show);
      } else {
        show();
      }
    }
  }

  /* Public surface. `reopen` is what the footer link calls, so a choice can
     always be changed -- withdrawing consent has to be as easy as giving it. */
  window.clipforgeConsent = {
    granted: granted,
    onGrant: onGrant,
    available: optional.slice(),
    reopen: function () {
      if (!optional.length) return false;
      if (node) { node.hidden = false; } else { show(); }
      return true;
    },
    revoke: function () {
      try { window.localStorage.removeItem(KEY); } catch (e) {}
      state = null;
    }
  };

  /* Any link marked as the preferences control reopens the notice in place
     rather than navigating, when there is something to decide. */
  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("[data-cookie-prefs]");
    if (!link) return;
    if (window.clipforgeConsent.reopen()) event.preventDefault();
  });
})();
