/* ClipForge — Studio front end.
   One config, one button. Home mirrors the desktop app's status panel; Settings
   is a flat list of grouped rows generated from the server's schema. */

const state = {
  user: null,
  studio: null,
  schema: null,
  settings: {},
  dirty: false,
  jobs: [],
  poll: null,
  // A plan chosen on the landing page, carried through sign-in so checkout
  // resumes on the other side instead of dumping them on the dashboard.
  pendingPlan: new URLSearchParams(location.search).get('plan'),
  // Set when a render agent sent the browser here to be approved.
  pairCode: '',
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(message, ms = 3800) {
  const el = $('toast');
  el.textContent = message;
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), ms);
}

async function api(path, { method = 'GET', body } = {}) {
  const options = { method, credentials: 'same-origin', headers: {} };
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (response.status === 401) { state.user = null; showGate(); throw new Error('Please sign in.'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

/* ------------------------------------------------------------- auth ---- */
let authMode = 'login';
document.querySelectorAll('.tab').forEach((tab) => {
  tab.onclick = () => {
    authMode = tab.dataset.mode;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === tab));
    // Only the label, never the button: its textContent also holds the arrow
    // that slides on hover, and rewriting the lot would delete it.
    $('auth-submit').querySelector('.label').textContent =
      authMode === 'login' ? 'Sign in' : 'Create account';
    $('auth-error').textContent = '';
  };
});

$('auth-form').onsubmit = async (event) => {
  event.preventDefault();
  $('auth-submit').disabled = true;
  $('auth-error').textContent = '';
  try {
    const data = await api(`/api/auth/${authMode}`, {
      method: 'POST',
      body: { email: $('email').value.trim(), password: $('password').value },
    });
    state.user = data.user;
    await enterApp();
  } catch (err) {
    $('auth-error').textContent = err.message;
  } finally {
    $('auth-submit').disabled = false;
  }
};

$('logout').onclick = async () => {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  state.user = null;
  showGate();
};

function showGate() {
  clearInterval(state.poll);
  $('gate').classList.remove('hidden');
  $('app').classList.add('hidden');

  // Someone who clicked a price wants to buy, not to read a sign-in form.
  // Say what happens next and default them to creating an account.
  if (state.pendingPlan) {
    $('gate-intent').textContent =
      `Create an account to continue to ${state.pendingPlan} checkout.`;
    $('gate-intent').classList.remove('hidden');
    const signup = document.querySelector('.tab[data-mode="signup"]');
    if (signup && authMode !== 'signup') signup.click();
  }
}

async function enterApp() {
  $('gate').classList.add('hidden');
  $('app').classList.remove('hidden');
  await Promise.all([loadStudio(), loadSettings()]);
  state.poll = setInterval(tick, 2500);

  // Covers both ways in: already signed in at load, and signed in just now.
  if (state.pairCode) showPair();

  // Resume a purchase started from the landing page before anything else.
  if (state.pendingPlan) {
    const plan = state.pendingPlan;
    state.pendingPlan = null;
    history.replaceState({}, '', '/app');
    await startCheckout(plan);
    return;
  }
  // Setup, not the tour. The tour explains the product and the guide is what
  // actually configures it, and until now the explaining was automatic while
  // the configuring sat behind a link on the settings screen. So a new
  // subscriber met a 79-field form and a red blocker before anyone had asked
  // them a single question. The tour still runs, straight after.
  //
  // Not while a pairing is waiting. Someone who arrived from an agent has a
  // program open on another screen polling for their answer, and a setup
  // wizard is not the thing to put in front of them first.
  if (state.studio && !state.studio.onboarded && !state.pairCode) {
    openGuide({ firstRun: true });
  }
}

async function startCheckout(plan) {
  if (state.user && state.user.plan === plan) {
    toast(`You are already on ${plan}.`);
    return;
  }
  toast('Taking you to checkout…');
  try {
    const { url } = await api(`/api/billing/checkout?plan=${encodeURIComponent(plan)}`,
                              { method: 'POST' });
    window.location = url;
  } catch (err) {
    // Billing off, or that plan has no price configured. Land them somewhere
    // useful rather than on a dead end.
    toast(err.message);
    document.querySelector('.tabitem[data-tab="activity"]').click();
    setTimeout(() => $('plans')?.scrollIntoView({ block: 'center' }), 400);
  }
}

/* -------------------------------------------------------------- nav ---- */
const NAV = [...document.querySelectorAll('.tabitem')];

function showTab(name, { focus = false } = {}) {
  NAV.forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', String(on));
    // Roving tabindex: one stop for the whole tablist, arrows move within it.
    t.tabIndex = on ? 0 : -1;
    if (on && focus) t.focus();
  });
  document.querySelectorAll('.screen').forEach((s) => s.classList.add('hidden'));
  $(`tab-${name}`).classList.remove('hidden');
  window.scrollTo(0, 0);
  if (name === 'history') loadJobs();
  if (name === 'activity') { loadUploads(); loadSources(); loadPlans(); loadAgent(); }
  // Build the preview only when the screen showing it is opened, so it never
  // costs an ffmpeg run for someone who is not looking at it.
  if (name === 'settings') { fillPreviewClips(); previewSoon(150); }
}

NAV.forEach((item, index) => {
  item.onclick = () => showTab(item.dataset.tab);
  item.onkeydown = (event) => {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (event.key in keys) {
      event.preventDefault();
      const next = (index + keys[event.key] + NAV.length) % NAV.length;
      showTab(NAV[next].dataset.tab, { focus: true });
    } else if (event.key === 'Home') {
      event.preventDefault();
      showTab(NAV[0].dataset.tab, { focus: true });
    } else if (event.key === 'End') {
      event.preventDefault();
      showTab(NAV[NAV.length - 1].dataset.tab, { focus: true });
    }
  };
});

/* ------------------------------------------------------------- home ---- */
const WORKING = ['queued', 'sourcing', 'curating', 'rendering'];
const STAGE_PCT = { queued: 8, sourcing: 35, curating: 60, rendering: 88 };

async function loadStudio() {
  const studio = await api('/api/studio');
  state.studio = studio;
  renderHome();
}

function renderHome() {
  const s = state.studio;
  if (!s) return;

  // Hero
  const busy = s.busy;
  const icon = $('hero-icon');
  icon.classList.remove('busy', 'bad');
  if (busy) {
    icon.textContent = '◌';
    icon.classList.add('busy');
    $('hero-title').textContent = 'Working';
    $('hero-sub').textContent = busy.stage || busy.status;
    $('hero-bar').classList.remove('hidden');
    $('hero-bar').firstElementChild.style.width = `${STAGE_PCT[busy.status] || 10}%`;
  } else if (s.blocked_by.length) {
    icon.textContent = '!';
    icon.classList.add('bad');
    $('hero-title').textContent = 'Not ready';
    $('hero-sub').textContent = `Needs: ${s.blocked_by.join(', ')}`;
    $('hero-bar').classList.add('hidden');
  } else {
    icon.textContent = '▶';
    $('hero-title').textContent = 'Ready';
    $('hero-sub').textContent = 'Press Publish to run the pipeline';
    $('hero-bar').classList.add('hidden');
  }
  $('publish').disabled = !!busy;
  $('dryrun').disabled = !!busy;

  // Status rows
  $('status-rows').innerHTML = s.status.map((row) => {
    const pill = { ready: '', action: ' warn', off: ' off' }[row.state] ?? '';
    const text = { ready: 'Ready', action: 'Action needed', off: 'Off' }[row.state];
    const connect = row.id === 'youtube' && row.state === 'action'
      ? `<button class="linkish" id="connect-youtube">${
          row.action === 'setup-publishing' ? 'Set up publishing' : 'Connect'
        }</button>` : '';
    return `<div class="row">
      <span class="row-label">${esc(row.label)}
        ${row.detail ? `<span class="row-sub">${esc(row.detail)} ${connect}</span>` : ''}</span>
      <span class="pill${pill}">${text}</span>
    </div>`;
  }).join('');

  const connectBtn = $('connect-youtube');
  if (connectBtn) {
    // No Google project yet means there is nothing to sign in to, so the
    // button opens the walkthrough that creates one rather than a consent
    // screen that would refuse.
    const row = s.status.find((r) => r.id === 'youtube') || {};
    connectBtn.onclick = row.action === 'setup-publishing'
      ? openPublishing : connectYouTube;
  }

  // Automation
  const auto = s.automation;
  $('automate-toggle').checked = auto.enabled;
  $('automate-toggle').disabled = !auto.allowed;
  $('automate-time').value = auto.time;
  $('automate-tz').value = auto.timezone;
  $('automation-note').textContent = auto.allowed
    ? 'Runs on our servers — nothing needs to stay open.'
    : 'Daily automation is included with Starter and Pro.';

  // Overview
  const o = s.overview;
  $('overview-rows').innerHTML = `
    <div class="row"><span class="row-label">Sources</span>
      <span class="row-value">${esc((o.source_names || []).join(', ') || 'none')}</span></div>
    <div class="row"><span class="row-label">Visibility</span>
      <span class="row-value">${esc(o.visibility)}</span></div>
    <div class="row"><span class="row-label">Publish after render</span>
      <span class="row-value">${o.auto_upload ? 'yes' : 'no'}</span></div>
    <div class="row"><span class="row-label">Per run</span>
      <span class="row-value">${o.clips_per_run} clips · ${o.length}s</span></div>
    <div class="row"><span class="row-label">Published</span>
      <span class="row-value">${o.published} of ${o.rendered}</span></div>`;

  $('plan-note').textContent =
    `${s.plan.id} plan · ${s.plan.renders_left} of ${s.plan.renders_total} runs left this month`
    + (s.plan.watermark ? ' · videos are watermarked' : '');
}

async function tick() {
  const wasBusy = !!state.studio?.busy;
  await loadStudio().catch(() => {});
  const nowBusy = !!state.studio?.busy;
  if (wasBusy && !nowBusy) {
    await loadJobs().catch(() => {});
    const last = state.jobs[0];
    if (last?.upload_state === 'uploaded') toast('Published to YouTube.');
    else if (last?.status === 'rejected') toast('Rejected: retention too low. Nothing was charged.');
    else if (last?.status === 'failed') toast(last.error || 'The run failed.');
    else if (last?.status === 'done') toast('Video ready in History.');
  }
}

$('publish').onclick = () => startRun(false);
$('dryrun').onclick = () => startRun(true);

async function startRun(dry) {
  $('publish').disabled = true;
  $('dryrun').disabled = true;
  try {
    await api('/api/studio/run', { method: 'POST', body: { dry_run: dry } });
    toast(dry ? 'Dry run started — it will not publish.' : 'Publishing…');
    await loadStudio();
  } catch (err) {
    toast(err.message);
    $('publish').disabled = false;
    $('dryrun').disabled = false;
  }
}

async function saveAutomation() {
  try {
    await api('/api/studio/automation', {
      method: 'PUT',
      body: {
        enabled: $('automate-toggle').checked,
        time: $('automate-time').value || '09:00',
        timezone: $('automate-tz').value.trim(),
      },
    });
    await loadStudio();
    toast($('automate-toggle').checked ? 'Daily runs on.' : 'Daily runs off.');
  } catch (err) {
    toast(err.message);
    await loadStudio();
  }
}
$('automate-toggle').onchange = saveAutomation;
$('automate-time').onchange = saveAutomation;
$('automate-tz').onchange = saveAutomation;

async function connectYouTube() {
  try {
    const { url } = await api('/api/youtube/connect');
    const popup = window.open(url, 'clipforge-youtube', 'width=520,height=680');
    const timer = setInterval(async () => {
      if (popup && popup.closed) {
        clearInterval(timer);
        await loadStudio();
        if (state.studio.youtube.connected) toast(`Connected: ${state.studio.youtube.channel}`);
      }
    }, 900);
  } catch (err) { toast(err.message); }
}

/* --------------------------------------------------------- settings ---- */
async function loadSettings() {
  const data = await api('/api/studio/settings');
  state.schema = data.schema;
  state.settings = data.settings;
  state.dirty = false;
  renderSettings();
}

function renderSettings() {
  // Each group is one block so the desktop grid can lay them out in columns
  // without splitting a heading from its rows.
  $('settings-groups').innerHTML = state.schema.groups.map((group) => `
    <section class="setting-group" aria-labelledby="g-${group.id}">
      <h2 class="group-title" id="g-${group.id}">${esc(group.name)}</h2>
      <div class="rows">${group.fields.map(rowHtml).join('')}</div>
      <p class="note">${esc(group.blurb)}</p>
    </section>`).join('');
  bindSettings();
  $('settings-status').textContent = '';
}

function rowHtml(field) {
  const value = state.settings[field.key] ?? field.default;
  const id = `s-${field.key}`;

  if (field.kind === 'bool') {
    return `<div class="row"><span class="row-label">${esc(field.label)}</span>
      <label class="switch"><input type="checkbox" id="${id}" data-key="${field.key}"
        ${value ? 'checked' : ''}><span class="track"></span></label></div>`;
  }
  if (field.kind === 'select' || field.options) {
    return `<div class="row"><span class="row-label">${esc(field.label)}</span>
      <select class="row-input" id="${id}" data-key="${field.key}">
        ${field.options.map((o) => `<option value="${esc(o)}"
          ${String(o) === String(value) ? 'selected' : ''}>${esc(o)}</option>`).join('')}
      </select></div>`;
  }
  if (field.kind === 'colour') {
    return `<div class="row"><span class="row-label">${esc(field.label)}</span>
      <input type="color" class="swatch" id="${id}" data-key="${field.key}" value="${esc(value)}"></div>`;
  }
  if (field.kind === 'list') {
    /* A field may carry its own placeholder where "one per line" is not enough
       of a hint -- a box wanting a pasted URL should show the shape of one. */
    const hint = field.placeholder || 'one per line';
    return `<div class="row stacked"><span class="row-label">${esc(field.label)}</span>
      <textarea class="row-input" id="${id}" data-key="${field.key}"
        placeholder="${esc(hint)}">${esc((value || []).join('\n'))}</textarea></div>`;
  }
  if (field.kind === 'int' || field.kind === 'float') {
    const step = field.kind === 'float' ? '0.05' : '1';
    return `<div class="row"><span class="row-label">${esc(field.label)}</span>
      <input type="number" class="row-input right" id="${id}" data-key="${field.key}"
        value="${value}" step="${step}"
        ${field.min !== undefined ? `min="${field.min}"` : ''}
        ${field.max !== undefined ? `max="${field.max}"` : ''}></div>`;
  }
  if (field.multiline) {
    return `<div class="row stacked"><span class="row-label">${esc(field.label)}</span>
      <textarea class="row-input" id="${id}" data-key="${field.key}">${esc(value)}</textarea></div>`;
  }
  return `<div class="row"><span class="row-label">${esc(field.label)}</span>
    <input type="text" class="row-input right" id="${id}" data-key="${field.key}"
      value="${esc(value)}" placeholder="—"></div>`;
}

function bindSettings() {
  const kinds = {};
  state.schema.groups.forEach((g) => g.fields.forEach((f) => { kinds[f.key] = f.kind; }));

  $('settings-groups').querySelectorAll('[data-key]').forEach((input) => {
    input.oninput = () => {
      const key = input.dataset.key;
      const kind = kinds[key];
      if (kind === 'bool') state.settings[key] = input.checked;
      else if (kind === 'list') {
        state.settings[key] = input.value.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
      } else if (kind === 'int') state.settings[key] = parseInt(input.value, 10);
      else if (kind === 'float') state.settings[key] = parseFloat(input.value);
      else state.settings[key] = input.value;
      state.dirty = true;
      $('settings-status').textContent = 'Unsaved changes';

      // Show the effect of the edit without waiting for a save.
      if (key === 'clips') fillPreviewClips();
      previewSoon();
    };
    if (input.type === 'checkbox' || input.tagName === 'SELECT') input.onchange = input.oninput;
  });
}

$('settings-save').onclick = async () => {
  $('settings-save').disabled = true;
  try {
    const { settings, notice } = await api('/api/studio/settings', {
      method: 'PUT', body: { settings: state.settings },
    });
    state.settings = settings;
    state.dirty = false;
    renderSettings();
    await loadStudio();
    /* A value the plan capped has to say so. Re-rendering shows the reduced
       number in the box, which on its own looks like the edit was thrown
       away rather than limited -- and the run that follows is then the wrong
       length for a reason nothing on screen explains. */
    if (notice) {
      $('settings-status').textContent = notice;
      toast(notice, 7000);
    } else {
      $('settings-status').textContent = 'Saved';
      toast('Settings saved.');
    }
  } catch (err) {
    $('settings-status').textContent = err.message;
  } finally {
    $('settings-save').disabled = false;
  }
};

/* ---------------------------------------------------------- presets ---- */
$('open-presets').onclick = async () => {
  try {
    const { presets } = await api('/api/presets');
    $('presets-list').innerHTML = presets.map((p) => `
      <button class="row tappable stacked" data-preset="${p.id}">
        <span class="row-label">${esc(p.name)}</span>
        <span class="row-sub">${esc(p.description)}</span>
      </button>`).join('');
    $('presets-list').querySelectorAll('[data-preset]').forEach((button) => {
      button.onclick = async () => {
        try {
          const data = await api(`/api/presets/${button.dataset.preset}/apply`, { method: 'POST' });
          state.settings = data.settings;
          renderSettings();
          await loadStudio();
          $('presets-sheet').classList.add('hidden');
          toast(`Loaded ${data.applied}.`);
        } catch (err) { toast(err.message); }
      };
    });
    $('presets-sheet').classList.remove('hidden');
  } catch (err) { toast(err.message); }
};
$('presets-close').onclick = () => $('presets-sheet').classList.add('hidden');
$('presets-sheet').onclick = (e) => { if (e.target === $('presets-sheet')) $('presets-close').click(); };

/* ---------------------------------------------------------- history ---- */
async function loadJobs() {
  const { jobs } = await api('/api/jobs');
  state.jobs = jobs;
  const host = $('history-list');
  if (!jobs.length) {
    host.innerHTML = '<p class="note">Nothing yet. Press Publish on the Home tab.</p>';
    return;
  }

  host.innerHTML = jobs.map((job) => {
    const working = WORKING.includes(job.status);
    let pill = 'off', label = job.status;
    if (job.upload_state === 'uploaded') { pill = ''; label = 'published'; }
    else if (job.status === 'done') { pill = ''; label = job.dry_run ? 'dry run' : 'rendered'; }
    else if (working) { pill = 'warn'; label = job.status; }
    else if (['failed', 'rejected'].includes(job.status) || job.upload_state === 'failed') pill = 'bad';

/* Why this video contains clips you have seen before.

   A run that has run out of fresh footage still produces a video -- it reuses
   the clips published longest ago rather than failing, which is the right
   call. But said nowhere, the result is indistinguishable from a source that
   is being ignored, and the obvious conclusion is that the app is broken. The
   numbers are the whole answer: four candidates for a four-clip video means
   the pool is too small, not that the playlist went unread. */
function sourcingNote(job) {
  const s = job.sourcing || {};
  if (!s.candidates && !s.reused) return '';

  const bits = [];
  if (s.reused) {
    const left = s.unused_available || 0;
    bits.push(`${s.reused} of ${s.reused + left} clip(s) here have been `
      + 'used before');
    bits.push(left
      ? `only ${left} unused clip(s) were left to choose from`
      : 'nothing unused was left to choose from');
  }
  if (s.candidates !== undefined) {
    const dropped = s.rejected_by_filters || 0;
    bits.push(`${s.candidates} candidate(s) found`
      + (dropped ? `, ${dropped} dropped by your filters` : ''));
  }
  if (!bits.length) return '';

  const fix = s.reused
    ? ' Add more videos to the playlist, widen the search, or lower the clip count.'
    : '';
  return `<p class="meta">${esc(bits.join(' \u00b7 '))}.${esc(fix)}</p>`;
}

/* Which moment it cut, from where, and why.

   "It does not understand my niche" is the hardest complaint to act on,
   because a finished video shows the answer and never the reasoning. Four
   clips that feel wrong could be a bad playlist, a bad reading of the niche,
   or the right moments cut two seconds early, and nothing on screen told
   those apart. The timecode is the useful part: it can be opened in the
   source and checked. */
function momentList(job) {
  const chosen = (job.sourcing || {}).moments_chosen || [];
  if (!chosen.length) return '';
  return `<details class="moments">
    <summary>Where these ${chosen.length} clip(s) came from</summary>
    <ol>${chosen.map((m) => `<li>
      <b>${esc(m.label || 'Clip')}</b>
      <span class="meta">${esc(m.source || 'source')} \u00b7 ${esc(m.at || '')}${
        m.why ? ` \u00b7 ${esc(m.why)}` : ''}</span>
    </li>`).join('')}</ol>
  </details>`;
}

    const reasons = (job.retention?.reasons || []).slice(0, 2);
    return `<div class="job">
      <div class="job-head">
        <div><h3>${esc(job.title || 'Untitled')}</h3>
          <div class="meta">${job.duration ? `${job.duration}s` : ''}${
            job.size_bytes ? ` · ${(job.size_bytes / 1048576).toFixed(1)} MB` : ''}${
            job.retention_score ? ` · retention ${job.retention_score}` : ''}${
            job.automated ? ' · scheduled' : ''}</div></div>
        <span class="pill ${pill}">${esc(label)}</span>
      </div>
      ${working ? `<div class="meta">${esc(job.stage || '')}</div>` : ''}
      ${reasons.length ? `<ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
      ${sourcingNote(job)}
      ${momentList(job)}
      ${job.error ? `<p class="error">${esc(job.error)}</p>` : ''}
      ${job.upload_error ? (job.upload_state === 'failed'
        ? `<p class="error">Upload: ${esc(job.upload_error)}</p>`
        /* A skip is not a failure, and colouring it red taught people to
           ignore it. It is still said, because "Publish now" producing a file
           that went nowhere is the thing nobody could explain. */
        : `<p class="meta">${esc(job.upload_error)}</p>`) : ''}
      <div class="job-actions">
        ${job.youtube_url ? `<a href="${esc(job.youtube_url)}" target="_blank" rel="noopener">Watch on YouTube</a>` : ''}
        ${job.download_url ? `<a href="${job.download_url}" download>Download</a>` : ''}
        <button data-del="${job.id}">Delete</button>
      </div>
    </div>`;
  }).join('');

  host.querySelectorAll('[data-del]').forEach((button) => {
    button.onclick = async () => {
      await api(`/api/jobs/${button.dataset.del}`, { method: 'DELETE' }).catch(() => {});
      loadJobs();
    };
  });
}

/* --------------------------------------------------------- activity ---- */
async function loadUploads() {
  const { uploads } = await api('/api/uploads');
  $('uploads').innerHTML = uploads.length
    ? uploads.map((u) => `<div class="row"><span class="row-label">${esc(u.name)}</span>
        <span class="row-value">${(u.size / 1048576).toFixed(1)} MB
          <button class="linkish" data-rm="${esc(u.name)}">remove</button></span></div>`).join('')
    : '<div class="row"><span class="row-value">No uploads yet.</span></div>';

  $('uploads').querySelectorAll('[data-rm]').forEach((b) => {
    b.onclick = async () => {
      await api(`/api/uploads/${encodeURIComponent(b.dataset.rm)}`, { method: 'DELETE' });
      loadUploads();
    };
  });
}

async function loadSources() {
  const { sources } = await api('/api/sources');
  $('sources').innerHTML = sources.map((s) => {
    // A source can be switched on and installed and still be refused, because
    // it is not cleared for reuse. Say "blocked", not "ready".
    let pill = 'off', label = 'off';
    if (s.enabled && !s.permitted) { pill = 'bad'; label = 'blocked'; }
    else if (s.enabled && s.configured) { pill = ''; label = 'ready'; }
    else if (s.enabled) { pill = 'warn'; label = s.needs_key ? 'needs key' : 'unavailable'; }
    return `<div class="row"><span class="row-label">${esc(s.label)}
      <span class="row-sub">${esc(s.licence)}</span></span>
      <span class="pill ${pill}">${label}</span></div>`;
  }).join('');
}

async function loadAgent() {
  const state_ = await api('/api/agent/status');
  const seen = state_.last_seen
    ? new Date(state_.last_seen).toLocaleString()
    : 'not yet';

  $('agent-rows').innerHTML = `
    <div class="row"><span class="row-label">Status
      <span class="row-sub">${state_.paired
        ? 'An agent on your own machine can claim your runs.'
        : 'Runs happen on our servers.'}</span></span>
      <span class="pill ${state_.paired ? '' : 'off'}">${state_.paired ? 'paired' : 'not paired'}</span></div>
    ${state_.paired ? `<div class="row"><span class="row-label">Last seen</span>
      <span class="row-value">${esc(seen)}</span></div>` : ''}`;

  // No "pair" button here any more. Pairing starts at the agent, because the
  // agent is the thing that needs the token and it is the only participant
  // that can put the token somewhere useful without a person carrying it.
  $('agent-actions').innerHTML = state_.paired
    ? '<button class="ghost danger" id="agent-unpair">Unpair</button>'
    : '';

  $('agent-token').classList.toggle('hidden', state_.paired);
  if (!state_.paired) {
    // Only offer the download when there is one. A button that goes nowhere
    // is worse than the sentence explaining where to get it.
    const step1 = state_.download_url
      ? `<li>Download it and put it in a folder of its own.</li>`
      : `<li>Get <code>ClipForgeAgent.exe</code>, or run the agent from
           source, and put it in a folder of its own.</li>`;
    $('agent-token').innerHTML = `
      <p class="note"><b>Run the agent and it pairs itself.</b> Start it and it
        opens this site to ask for one click. There is no token to copy and no
        file to edit.</p>
      <ol class="steps-list">
        ${step1}
        <li>Install ffmpeg if you have not:
          <code>winget install Gyan.FFmpeg</code></li>
        <li>Run it, and approve the code it shows you.</li>
      </ol>
      ${state_.download_url ? `<div class="actions-row">
        <a class="ghost btn-link" id="agent-download"
           href="${esc(state_.download_url)}">Download the agent</a>
      </div>` : ''}`;
  }

  // Why anyone would want this, in the one place they are deciding.
  $('agent-note').textContent = state_.local_rendering
    ? 'This server does not render anything itself, so runs wait until your '
      + 'agent is running.'
    : 'Optional. Running the agent uses your own computer and connection, '
      + 'which is the only way to reach footage our servers are blocked from.';

  if ($('agent-unpair')) $('agent-unpair').onclick = async () => {
    if (!confirm('The agent on that machine stops immediately. Continue?')) return;
    await api('/api/agent/token', { method: 'DELETE' });
    loadAgent();
  };
}

async function loadPlans() {
  const [{ plans, billing_note: note }, me] = await Promise.all([
    api('/api/plans'), api('/api/me'),
  ]);
  state.user = me;
  $('account-rows').innerHTML = `
    <div class="row"><span class="row-label">Email</span>
      <span class="row-value">${esc(me.email)}</span></div>
    <div class="row"><span class="row-label">Plan</span>
      <span class="row-value accent">${esc(me.plan)}</span></div>
    <div class="row"><span class="row-label">Runs left</span>
      <span class="row-value">${me.renders_left} of ${me.limits.renders_per_month}</span></div>`;

  $('plans').innerHTML = plans.map((p) => {
    let right;
    if (me.plan === p.id) right = '<span class="pill">current</span>';
    else if (p.id === 'free') right = `<span class="row-value">${esc(p.price)}</span>`;
    else if (p.purchasable) {
      right = `<button class="ghost" data-buy="${p.id}">${esc(p.price)} &mdash; upgrade</button>`;
    } else {
      right = `<span class="row-value">${esc(p.price)}</span>`;
    }
    return `<div class="row"><span class="row-label">${esc(p.id)}
      <span class="row-sub">${p.renders_per_month}/mo · ${p.max_clips} clips · ${
        p.watermark ? 'watermarked' : 'no watermark'}${
        p.id === 'free' ? '' : ' · daily automation'}</span></span>
      ${right}</div>`;
  }).join('')
  // Say why the upgrade buttons are missing instead of showing a dead control.
  + (note ? `<div class="row"><span class="row-sub">${esc(note)}</span></div>` : '');

  $('plans').querySelectorAll('[data-buy]').forEach((b) => {
    b.onclick = () => startCheckout(b.dataset.buy);
  });
}

$('manage-billing').onclick = async () => {
  try {
    const { url } = await api('/api/billing/portal', { method: 'POST' });
    window.location = url;
  } catch (err) { toast(err.message); }
};

/* ------------------------------------------------------------------ data --
   Access and erasure. Both are promised on /privacy, so both are reachable
   from the screen that page names, in the number of clicks it implies. */

/* The export is a plain link to an endpoint that already answers with
   Content-Disposition: attachment, matching how the agent download and the
   finished renders work. No blob, no object URL, and nothing to clean up. */

$('delete-account').onclick = async () => {
  /* Two prompts, because the server asks for two things and neither should be
     satisfiable by one stray click. The typed word goes first: someone who is
     not sure stops here, before being asked for a password. */
  const confirmation = window.prompt(
    'This deletes your account, your uploads and your renders. It cannot be '
    + 'undone.\n\nType DELETE to confirm.');
  if (confirmation === null) return;
  if (confirmation.trim().toUpperCase() !== 'DELETE') {
    toast('Not deleted. You need to type DELETE exactly.');
    return;
  }

  const password = window.prompt('Enter your password to confirm.');
  if (!password) return;

  try {
    await api('/api/me/delete', {
      method: 'POST',
      body: { password, confirm: 'DELETE' },
    });
    /* The session is gone server-side and the cookie has been cleared, so
       there is nothing left to show. A reload lands on the signed-out gate. */
    state.user = null;
    toast('Account deleted.');
    setTimeout(() => { window.location = '/'; }, 1200);
  } catch (err) {
    toast(err.message);
  }
};

const drop = $('drop');
$('browse').onclick = () => $('file-input').click();
$('file-input').onchange = (e) => uploadFiles([...e.target.files]);
['dragenter', 'dragover'].forEach((t) =>
  drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((t) =>
  drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', (e) => uploadFiles([...e.dataTransfer.files]));

async function uploadFiles(files) {
  const videos = files.filter((f) => f.type.startsWith('video/')
    || /\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(f.name));
  if (!videos.length) return toast('Those need to be video files.');

  for (const [index, file] of videos.entries()) {
    $('upload-hint').textContent = `Uploading ${index + 1} of ${videos.length}: ${file.name}`;
    const form = new FormData();
    form.append('file', file);
    try { await api('/api/uploads', { method: 'POST', body: form }); }
    catch (err) { toast(`${file.name}: ${err.message}`); }
  }
  $('upload-hint').textContent = 'Your own footage has nothing to claim.';
  toast(`Uploaded ${videos.length} clip(s).`);
  loadUploads();
}

/* ---------------------------------------------------------- pair ------ */
/* An agent sent the browser here with a code. The person approves it, the
   server mints a token, and the agent -- which is sitting in a poll loop --
   collects it. Nobody handles the secret.

   Arriving signed out is normal rather than exceptional: the agent has just
   been installed, often on a machine whose browser has never seen this site.
   So this waits for the sign-in to finish rather than assuming a session. */
function pairCodeFromUrl() {
  if (location.pathname.replace(/\/+$/, '') !== '/pair') return '';
  return (new URLSearchParams(location.search).get('code') || '')
    .trim().toUpperCase().slice(0, 9);
}

function closePair() {
  $('pair').classList.add('hidden');
  state.pairCode = '';
  // The setup it displaced, now that the screen is free.
  if (state.studio && !state.studio.onboarded) openGuide({ firstRun: true });
  // Leave the URL clean so a refresh, or a bookmark, does not reopen a code
  // that has already been used.
  history.replaceState({}, '', '/app');
}

async function showPair() {
  const code = state.pairCode;
  if (!code) return;
  const panel = $('pair');
  panel.classList.remove('hidden');

  const lead = $('pair-lead');
  const rows = $('pair-rows');
  const actions = $('pair-actions');
  const warn = $('pair-warn');
  const done = (message) => {
    lead.textContent = message;
    rows.innerHTML = '';
    warn.textContent = '';
    actions.innerHTML = '<button class="primary" id="pair-close">Done</button>';
    $('pair-close').onclick = closePair;
  };

  let info;
  try {
    info = await api(`/api/agent/pair/lookup?code=${encodeURIComponent(code)}`);
  } catch {
    done('Could not check that code. Try starting the agent again.');
    return;
  }

  if (!info.found) {
    done(`The code ${code} has expired or was never issued. Start the agent `
         + 'again and it will show you a new one.');
    return;
  }
  if (info.approved) {
    done(`${code} has already been used. If your agent is still waiting, `
         + 'start it again for a fresh code.');
    return;
  }

  lead.textContent = 'A render agent is asking to work for your account. '
    + 'It will claim your runs and render them on that machine.';
  rows.innerHTML = `
    <div class="row"><span class="row-label">Computer</span>
      <span class="row-value">${esc(info.label || 'not reported')}</span></div>
    <div class="row"><span class="row-label">Code</span>
      <span class="row-value pair-code">${esc(info.code)}</span></div>`;

  // The one real weakness of this flow is somebody being talked into
  // approving a code that is not theirs, so say so where the decision is.
  warn.textContent = info.already_paired
    ? 'You already have an agent paired. Approving this replaces it, and the '
      + 'old one stops immediately. If you did not just start an agent '
      + 'yourself, close this page.'
    : 'If you did not just start the agent on that computer, close this page '
      + 'and do not approve it.';

  actions.innerHTML = `
    <button class="primary" id="pair-yes">Pair it</button>
    <button class="ghost" id="pair-no">Not now</button>`;
  $('pair-no').onclick = closePair;
  $('pair-yes').onclick = async () => {
    $('pair-yes').disabled = true;
    $('pair-yes').textContent = 'Pairing...';
    try {
      await api('/api/agent/pair/approve', {
        method: 'POST', body: { code: info.code },
      });
    } catch (err) {
      lead.textContent = err.message || 'That did not work. Try again.';
      $('pair-yes').disabled = false;
      $('pair-yes').textContent = 'Pair it';
      return;
    }
    done('Paired. The agent picks this up within a few seconds and starts '
         + 'working -- you can close this page.');
    loadAgent();
  };
}

/* ------------------------------------------------------- preview ------ */
/* The frame is rendered server-side by the real pipeline, so it cannot drift
   from what the video will look like. Requests are debounced and the previous
   one is abandoned, because people edit settings faster than ffmpeg runs. */
let previewTimer = null;
let previewRun = 0;

function previewSoon(delay = 700) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, delay);
}

async function refreshPreview() {
  const img = $('preview-img');
  const state = $('preview-state');
  if (!img) return;

  const run = ++previewRun;
  state.textContent = 'Building preview…';
  state.classList.remove('hidden');

  const atClip = Number($('preview-clip').value) || 2;
  try {
    const response = await fetch('/api/studio/preview', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: state_settings(), at_clip: atClip }),
    });
    if (run !== previewRun) return;          // a newer edit already won
    if (!response.ok) throw new Error(`preview failed (${response.status})`);

    const blob = await response.blob();
    if (run !== previewRun) return;
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    const url = URL.createObjectURL(blob);
    img.dataset.url = url;
    img.src = url;
    state.classList.add('hidden');
  } catch (err) {
    if (run !== previewRun) return;
    state.textContent = 'Preview unavailable right now.';
    state.classList.remove('hidden');
  }
  refreshReview();
}

function state_settings() {
  return state.settings;
}

function fillPreviewClips() {
  const select = $('preview-clip');
  if (!select) return;
  const count = Math.max(2, Math.min(state.settings.clips || 5, 12));
  const chosen = Math.min(Number(select.value) || 2, count);
  select.innerHTML = Array.from({ length: count }, (_, i) =>
    `<option value="${i + 1}" ${i + 1 === chosen ? 'selected' : ''}>${i + 1} of ${count}</option>`).join('');
}

async function refreshReview() {
  const host = $('review-list');
  if (!host) return;
  try {
    const data = await api('/api/studio/review', {
      method: 'POST', body: { settings: state.settings },
    });
    host.innerHTML = renderFindings(data);
  } catch { host.innerHTML = ''; }
}

function renderFindings(data) {
  if (!data.findings.length) {
    return '<div class="finding review-ok">Nothing to flag &mdash; this should produce a video.</div>';
  }
  const order = { blocker: 0, warning: 1, tip: 2 };
  return [...data.findings]
    .sort((a, b) => order[a.level] - order[b.level])
    .map((f) => `<div class="finding ${f.level}">
      <b>${esc(f.title)}</b>
      <span class="detail">${esc(f.detail)}</span>
      ${f.fix ? `<span class="fix">${esc(f.fix)}</span>` : ''}
    </div>`).join('');
}

if ($('preview-refresh')) $('preview-refresh').onclick = () => refreshPreview();
if ($('preview-clip')) $('preview-clip').onchange = () => refreshPreview();

/* -------------------------------------------------- guided setup ------ */
/* A walkthrough that actually configures the niche, checking each answer
   against what the pipeline can deliver. The last step will not let someone
   finish on a configuration that cannot produce a video. */
const GUIDE = [
  {
    title: 'What are you making?',
    choiceKey: 'shape',
    intro: `<p>Pick the <b>shape</b> of video. This decides the pacing and what
      goes on screen, which matters more for retention than the topic does.</p>`,
    render: () => choices('shape', [
      { id: 'top5', title: 'A ranked countdown',
        note: 'Numbered list, best clip last. The strongest format for holding attention.' },
      { id: 'funny', title: 'Loose highlights',
        note: 'No ranking. The best moment goes first instead of last.' },
      { id: 'memes', title: 'Fast meme cut',
        note: 'Very short clips, big captions, built for rewatching.' },
      { id: 'show', title: 'One specific TV show or series',
        note: 'Reads a playlist of full episodes and cuts the moments out of them.' },
    ]),
    apply: async (value) => {
      const { presets } = await api('/api/presets');
      const preset = presets.find((p) => p.slug === value);
      if (preset) {
        const data = await api(`/api/presets/${preset.id}/apply`, { method: 'POST' });
        state.settings = data.settings;
      }
    },
  },
  {
    title: 'Where do the clips come from?',
    choiceKey: 'source',
    /* Asked of everybody, not only the "one show" preset. This question used
       to live inside a step gated on require_show_match, which only that
       preset sets -- so somebody picking "a ranked countdown", the first and
       most obvious option, was never asked where footage comes from and fell
       through to a keyword search. A search returns fan edits, scenes from
       the films and people reviewing the show at a desk, all of them honest
       matches for the words typed. That is how four finished videos came out
       mostly not being the show at all.

       Sourcing is orthogonal to shape, so it gets its own question. */
    intro: `<p>This decides whether the finished videos are any good, more
      than the pacing or the fonts or the length do.</p>`,
    render: () => choices('source', [
      { id: 'playlist', title: 'A YouTube playlist',
        note: 'Paste a playlist of full episodes. The good moments are found inside them and cut out.' },
      { id: 'uploads', title: 'Footage I upload myself',
        note: 'Your own clips. Nothing is searched for and nothing is downloaded.' },
    ]) + (youtubeUsable() ? '' : `<p class="hint warn">The YouTube source is
      switched off on this server, so only your own uploads can be used.</p>`),
    apply: (value) => {
      const wants = youtubeUsable() ? (value || 'uploads') : 'uploads';
      guideChoice.source = wants;
      state.settings.sources = wants === 'playlist'
        ? ['youtube', 'upload'] : ['upload'];
      if (wants === 'uploads') {
        // The show filter refuses clips that cannot be shown to come from one
        // programme. That question does not arise for your own footage, and
        // leaving it on with nothing to match against rejects every clip.
        state.settings.require_show_match = false;
      }
    },
  },
  {
    title: 'Which playlist?',
    skipUnless: () => guideChoice.source === 'playlist',
    intro: `<p>Open the playlist on YouTube and copy the address. Whatever is
      in it is what gets used &mdash; a playlist you chose is proof of what the
      footage is, which a search can never be.</p>
      <p>Full episodes are ideal. Anything longer than about a minute is
      searched rather than used whole, and several moments are cut from each,
      so a handful of episodes goes a long way.</p>`,
    render: () => field('source_playlists', 'Playlist links', 'textarea',
      (state.settings.source_playlists || []).join('\n'),
      'One link per line, e.g. https://www.youtube.com/playlist?list=PL...'),
    apply: (value, form) => {
      const links = splitLines(form.source_playlists);
      // Choosing "a YouTube playlist" and then pasting nothing lands on
      // exactly the configuration this step exists to prevent: discovery
      // falls back to a keyword search. The advice on the last step does say
      // so, but by then it reads as a complaint about a decision already
      // taken, and it is skippable. Refuse here instead.
      if (!links.length) {
        throw new Error('Paste a playlist link, or go back and choose your '
                        + 'own uploads instead.');
      }
      const unusable = links.filter((l) => !/[?&]list=|^[A-Z]{2}[\w-]{6,}$/.test(l));
      if (unusable.length === links.length) {
        throw new Error('That is not a playlist link — a usable one contains '
                        + '"list=" followed by an id. Open the playlist itself '
                        + 'on YouTube and copy the address from there.');
      }
      state.settings.source_playlists = links;
    },
  },
  {
    title: 'What should it look for?',
    skipUnless: () => guideChoice.source !== 'playlist',
    intro: `<p>These words are matched against your upload filenames, so
      leaving this empty uses everything you have uploaded.</p>`,
    render: () => field('search_terms', 'Search terms', 'textarea',
      (state.settings.search_terms || []).join('\n'),
      'One per line. e.g. "skateboard", "city at night"'),
    // Read the textarea, not the choice value: this step has no choice, and
    // `value` would be undefined -- which showed up in the preview as a
    // checklist entry reading "Undefined".
    apply: (value, form) => {
      state.settings.search_terms = splitLines(form.search_terms);
    },
  },
  {
    title: 'How long, and how many clips?',
    intro: `<p>Pace is what the retention gate scores hardest. More clips in
      less time reads as energetic; fewer, longer ones read as static.</p>`,
    render: () => `
      ${field('clips', 'Number of clips', 'number', state.settings.clips, '')}
      ${field('target_seconds', 'Total length (seconds)', 'number',
              state.settings.target_seconds, '')}
      <p class="hint" id="pace-note"></p>`,
    apply: (value, form) => {
      state.settings.clips = parseInt(form.clips, 10) || 5;
      state.settings.target_seconds = parseInt(form.target_seconds, 10) || 105;
    },
  },
  {
    title: 'Here is what it will look like',
    intro: `<p>Rendered by the same pipeline that makes the video. Check the
      banner text and where the numbered list sits.</p>`,
    preview: true,
    render: () => `
      ${field('banner_line1', 'Banner line 1', 'input',
              state.settings.banner_line1 || '', '{count} becomes the clip count')}
      ${field('banner_line2', 'Banner line 2', 'input',
              state.settings.banner_line2 || '', 'Your channel name works well here')}`,
    apply: (value, form) => {
      state.settings.banner_line1 = form.banner_line1;
      state.settings.banner_line2 = form.banner_line2;
    },
  },
];

let guideAt = 0;
let guideChoice = {};

/* What the server will actually let a job use. Offering "a YouTube playlist"
   on an install where the operator has not enabled unlicensed sources would
   walk somebody into a configuration the registry then refuses, and the only
   sign would be a run that finds nothing. */
let guideSources = [];

/* Whether this is somebody's first time. Setup comes first and the tour
   follows it, so the walkthrough explains a screen that is already configured
   rather than an empty one. */
let guideFirstRun = false;

/* The last review of what the answers add up to, so finishing can refuse a
   configuration that cannot produce a video -- which the comment at the top
   of GUIDE has always claimed happened, and which nothing enforced. */
let guideReview = null;

function youtubeUsable() {
  return guideSources.some((s) => s.name === 'youtube' && s.enabled
                                  && s.configured && s.permitted);
}

function choices(key, options) {
  return options.map((o) => `
    <button type="button" class="choice ${guideChoice[key] === o.id ? 'on' : ''}"
            data-choice="${key}" data-value="${o.id}">
      <b>${esc(o.title)}</b><span>${esc(o.note)}</span>
    </button>`).join('');
}

function field(name, label, kind, value, hint) {
  const control = kind === 'textarea'
    ? `<textarea data-field="${name}" placeholder="${esc(hint)}">${esc(value ?? '')}</textarea>`
    : `<input type="${kind}" data-field="${name}" value="${esc(value ?? '')}"
         placeholder="${esc(hint)}">`;
  return `<div class="guide-field">
    <label>${esc(label)}</label>${control}
    ${hint && kind !== 'textarea' ? `<span class="hint">${esc(hint)}</span>` : ''}
  </div>`;
}

function splitLines(value) {
  return String(value || '').split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}

function visibleGuideSteps() {
  return GUIDE.filter((s) => !s.skipUnless || s.skipUnless());
}

async function renderGuide() {
  const steps = visibleGuideSteps();
  guideAt = Math.max(0, Math.min(guideAt, steps.length - 1));
  const step = steps[guideAt];

  $('guide-step').textContent = `Step ${guideAt + 1} of ${steps.length}`;
  $('guide-title').textContent = step.title;
  $('guide-body').innerHTML = (step.intro || '') + step.render();
  $('guide-dots').innerHTML = steps.map((_, i) =>
    `<i class="${i === guideAt ? 'on' : ''}"></i>`).join('');
  $('guide-back').disabled = guideAt === 0;
  $('guide-next').textContent = guideAt === steps.length - 1 ? 'Save and finish' : 'Next';

  $('guide-body').querySelectorAll('[data-choice]').forEach((button) => {
    button.onclick = () => {
      guideChoice[button.dataset.choice] = button.dataset.value;
      $('guide-body').querySelectorAll(`[data-choice="${button.dataset.choice}"]`)
        .forEach((b) => b.classList.toggle('on', b === button));
    };
  });

  // Live pace feedback while they type, so the retention rule is visible
  // before it rejects anything.
  const paceNote = $('pace-note');
  if (paceNote) {
    const update = () => {
      const form = readGuideForm();
      const clips = parseInt(form.clips, 10) || 1;
      const secs = parseInt(form.target_seconds, 10) || 1;
      const cpm = clips / secs * 60;
      paceNote.textContent =
        `${cpm.toFixed(1)} cuts a minute — ` +
        (cpm < 8 ? 'too static; the retention gate will mark this down.'
         : cpm > 30 ? 'very fast; hard to follow.'
         : 'a good range.');
      paceNote.style.color = (cpm < 8 || cpm > 30) ? 'var(--warn)' : 'var(--good)';
    };
    $('guide-body').querySelectorAll('[data-field]').forEach((i) => { i.oninput = update; });
    update();
  }

  $('guide-preview').classList.toggle('hidden', !step.preview);
  $('guide-review').innerHTML = '';
  if (step.preview) await guidePreview();
}

function readGuideForm() {
  const out = {};
  $('guide-body').querySelectorAll('[data-field]').forEach((input) => {
    out[input.dataset.field] = input.value;
  });
  return out;
}

async function guidePreview() {
  try {
    const response = await fetch('/api/studio/preview', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: state.settings, at_clip: 2 }),
    });
    if (!response.ok) throw new Error('no preview');
    const blob = await response.blob();
    $('guide-img').src = URL.createObjectURL(blob);
  } catch {
    $('guide-preview').classList.add('hidden');
  }
  try {
    const data = await api('/api/studio/review', {
      method: 'POST', body: { settings: state.settings },
    });
    guideReview = data;
    $('guide-review').innerHTML = renderFindings(data);
  } catch { /* advice is a bonus, not a blocker */ }
}

async function openGuide({ firstRun = false } = {}) {
  guideAt = 0;
  guideChoice = {};
  guideFirstRun = firstRun;
  guideReview = null;
  try {
    ({ sources: guideSources } = await api('/api/sources'));
  } catch { guideSources = []; }

  // Seed the sourcing answer so pressing Next without touching anything still
  // produces a configuration that can run. A returning user keeps what they
  // already chose; a new one starts on the playlist, because the alternative
  // default is uploads-with-no-uploads, which is a blocker on first login.
  const hasPlaylist = (state.settings.source_playlists || []).length > 0;
  const usesYouTube = (state.settings.sources || []).includes('youtube');
  guideChoice.source = !youtubeUsable() ? 'uploads'
    : (firstRun || hasPlaylist || usesYouTube) ? 'playlist' : 'uploads';

  $('guide').classList.remove('hidden');
  await renderGuide();
}

$('guide-close').onclick = () => $('guide').classList.add('hidden');
$('guide').onclick = (e) => { if (e.target === $('guide')) $('guide-close').click(); };
$('open-guide').onclick = openGuide;

$('guide-back').onclick = async () => { guideAt -= 1; await renderGuide(); };

$('guide-next').onclick = async () => {
  const steps = visibleGuideSteps();
  const step = steps[guideAt];
  const button = $('guide-next');
  button.disabled = true;
  try {
    // Steps that offer choices name the key they store under; the rest read
    // their values from the form instead.
    await step.apply?.(guideChoice[step.choiceKey], readGuideForm());

    if (guideAt < visibleGuideSteps().length - 1) {
      guideAt += 1;
      await renderGuide();
    } else {
      const blockers = (guideReview?.findings || [])
        .filter((f) => f.level === 'blocker');
      if (blockers.length) {
        throw new Error(`${blockers[0].title}. ${blockers[0].fix || ''}`.trim());
      }
      const { settings } = await api('/api/studio/settings', {
        method: 'PUT', body: { settings: state.settings },
      });
      state.settings = settings;
      renderSettings();
      fillPreviewClips();
      previewSoon(0);
      await loadStudio();
      $('guide').classList.add('hidden');
      toast('Your niche is set up. Press Publish when ready.');
      // Now the tour, and only now: it points at the real controls, and it
      // makes far more sense over a screen that is already configured than
      // over an empty one somebody has not been asked anything about yet.
      if (guideFirstRun) {
        guideFirstRun = false;
        // Publishing before the tour, because it is the part that happens on
        // somebody else's website and the one most likely to be abandoned if
        // it is left to be discovered later. The tour follows it.
        pubThenTour = true;
        openPublishing();
      }
    }
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
  }
};


/* ------------------------------------------- publishing setup -------- */
/* Every account publishes through its own Google Cloud project.

   Not a preference: the YouTube Data API gives each project 10,000 units a
   day and one upload costs 1,600, so a single shared project is about six
   uploads a day across every customer there will ever be. Raising that needs
   an audit. A project the subscriber owns has its own ceiling, and reaching
   it needs nothing from anybody.

   The cost is that setup happens on somebody else's website, in a console
   most people have never opened, and a wall of text describing it does not
   work. So each step draws the screen being described and highlights the one
   thing to click. The drawings are schematic on purpose -- real screenshots
   of the Google console go stale within months and are somebody else's
   copyright. */

const PUB_LINKS = {
  project: 'https://console.cloud.google.com/projectcreate',
  library: 'https://console.cloud.google.com/apis/library/youtube.googleapis.com',
  consent: 'https://console.cloud.google.com/apis/credentials/consent',
  credentials: 'https://console.cloud.google.com/apis/credentials',
};

/* A schematic browser window, so each drawing reads as "a page you will see"
   rather than as an abstract diagram. */
function pubFrame(inner, height = 150) {
  return `<svg class="pub-svg" viewBox="0 0 420 ${height}" role="img"
       xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="418" height="${height - 2}" rx="8"
          fill="var(--surface-2)" stroke="var(--border)"/>
    <rect x="1" y="1" width="418" height="22" rx="8" fill="var(--surface)"/>
    <rect x="1" y="15" width="418" height="8" fill="var(--surface)"/>
    <circle cx="14" cy="12" r="3" fill="var(--border-firm)"/>
    <circle cx="24" cy="12" r="3" fill="var(--border-firm)"/>
    <circle cx="34" cy="12" r="3" fill="var(--border-firm)"/>
    <line x1="1" y1="23" x2="419" y2="23" stroke="var(--border)"/>
    ${inner}
  </svg>`;
}

/* The ring that says "this one". */
function pubRing(x, y, w, h) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="5" fill="none"
       stroke="var(--accent)" stroke-width="2"/>`;
}

function pubLabel(x, y, text, size = 9, fill = 'var(--muted)') {
  return `<text x="${x}" y="${y}" font-size="${size}" fill="${fill}"
       font-family="system-ui, sans-serif">${esc(text)}</text>`;
}

const PUB_ART = {
  project: () => pubFrame(`
    ${pubLabel(14, 40, 'Google Cloud', 11, 'var(--text)')}
    <rect x="96" y="30" width="120" height="18" rx="4" fill="var(--surface)"
          stroke="var(--border-firm)"/>
    ${pubLabel(104, 43, 'Select a project  ▾')}
    ${pubRing(94, 28, 124, 22)}
    ${pubLabel(14, 78, 'A panel opens. Top right of it:')}
    <rect x="250" y="88" width="90" height="20" rx="4" fill="var(--accent)"/>
    ${pubLabel(262, 102, 'NEW PROJECT', 9, '#fff')}
    ${pubRing(248, 86, 94, 24)}
    ${pubLabel(14, 130, 'Name it anything — "ClipForge" is fine.')}
  `),

  library: () => pubFrame(`
    ${pubLabel(14, 40, 'APIs & Services  ›  Library', 10, 'var(--text)')}
    <rect x="14" y="52" width="260" height="20" rx="4" fill="var(--surface)"
          stroke="var(--border-firm)"/>
    ${pubLabel(22, 66, 'youtube data api')}
    ${pubRing(12, 50, 264, 24)}
    <rect x="14" y="88" width="392" height="44" rx="6" fill="var(--surface)"
          stroke="var(--border)"/>
    ${pubLabel(26, 106, 'YouTube Data API v3', 10, 'var(--text)')}
    ${pubLabel(26, 120, 'Google LLC')}
    <rect x="316" y="98" width="76" height="22" rx="4" fill="var(--accent)"/>
    ${pubLabel(338, 113, 'ENABLE', 9, '#fff')}
    ${pubRing(314, 96, 80, 26)}
  `, 148),

  consent: () => pubFrame(`
    ${pubLabel(14, 40, 'OAuth consent screen', 10, 'var(--text)')}
    <circle cx="22" cy="58" r="5" fill="none" stroke="var(--border-firm)"/>
    ${pubLabel(34, 62, 'Internal  — not available to you')}
    <circle cx="22" cy="80" r="5" fill="var(--accent)"/>
    ${pubLabel(34, 84, 'External', 10, 'var(--text)')}
    ${pubRing(12, 70, 200, 20)}
    ${pubLabel(14, 110, 'Then: app name, your email, save.')}
    ${pubLabel(14, 128, 'Audience › Test users › + Add users — add your own', 9)}
    ${pubLabel(14, 141, 'Google address. Without it, sign-in is refused.', 9)}
  `, 156),

  client: () => pubFrame(`
    ${pubLabel(14, 40, 'Credentials  ›  Create credentials', 10, 'var(--text)')}
    <rect x="14" y="50" width="150" height="20" rx="4" fill="var(--surface)"
          stroke="var(--border-firm)"/>
    ${pubLabel(22, 64, 'OAuth client ID')}
    ${pubRing(12, 48, 154, 24)}
    ${pubLabel(14, 90, 'Application type')}
    <rect x="14" y="98" width="150" height="20" rx="4" fill="var(--surface)"
          stroke="var(--border-firm)"/>
    ${pubLabel(22, 112, 'Web application', 9, 'var(--text)')}
    ${pubRing(12, 96, 154, 24)}
    ${pubLabel(190, 90, 'Authorised redirect URIs')}
    <rect x="190" y="98" width="216" height="20" rx="4" fill="var(--surface)"
          stroke="var(--accent)"/>
    ${pubLabel(196, 112, 'paste the address from above', 8)}
    ${pubLabel(14, 140, 'The redirect URI must match exactly, or Google', 9)}
    ${pubLabel(14, 152, 'refuses the sign-in with redirect_uri_mismatch.', 9)}
  `, 166),
};

const PUB_STEPS = [
  {
    title: 'Publishing to your channel',
    body: () => `
      <p>To upload for you, ClipForge needs a <b>Google Cloud project</b> of
      your own. It takes about five minutes, once, and then it is done
      forever.</p>
      <p>Why yours and not ours: Google allows each project a fixed number of
      uploads per day. On a shared one, every customer would be competing for
      about six uploads a day between them. On your own, the allowance is
      yours alone.</p>
      <p class="hint">Not interested in automatic uploads? Choose <b>I will
      download them myself</b> below. Videos still get made; you post them
      yourself, and you can turn this on later.</p>
      <p><a class="pub-open" href="/connect" target="_blank" rel="noopener">Open
      these steps as a page &#8599;</a> &mdash; easier to follow on a second
      screen, or to send to whoever runs your Google account.</p>`,
  },
  {
    title: 'Create a project',
    body: () => `
      <p>Open the Google Cloud console and make a new project. Any name will
      do.</p>
      ${PUB_ART.project()}
      <p><a href="${PUB_LINKS.project}" target="_blank" rel="noopener"
        class="pub-open">Open the project page &#8599;</a></p>`,
  },
  {
    title: 'Turn on the YouTube API',
    body: () => `
      <p>With your new project selected, enable <b>YouTube Data API v3</b>.
      This is what lets anything upload on your behalf.</p>
      ${PUB_ART.library()}
      <p><a href="${PUB_LINKS.library}" target="_blank" rel="noopener"
        class="pub-open">Open the API page &#8599;</a></p>`,
  },
  {
    title: 'Set up the consent screen',
    body: () => `
      <p>This is the screen you will see when you connect your channel. Choose
      <b>External</b>, fill in an app name and your email, and save.</p>
      ${PUB_ART.consent()}
      <p><b>Do not skip the test user step.</b> Until the project is verified
      by Google, only accounts listed there may sign in &mdash; everyone else
      gets <i>Access blocked</i>. Add the Google account that owns your
      YouTube channel.</p>
      <p><a href="${PUB_LINKS.consent}" target="_blank" rel="noopener"
        class="pub-open">Open the consent screen &#8599;</a></p>`,
  },
  {
    title: 'Create the credentials',
    body: () => `
      <p>Now make an <b>OAuth client ID</b> of type <b>Web application</b>,
      and give it this exact redirect address:</p>
      <div class="pub-copy">
        <code id="pub-redirect">${esc(state.pubApp?.redirect_uri || '')}</code>
        <button class="ghost" id="pub-copy-btn" type="button">Copy</button>
      </div>
      ${PUB_ART.client()}
      <p><a href="${PUB_LINKS.credentials}" target="_blank" rel="noopener"
        class="pub-open">Open the credentials page &#8599;</a></p>`,
    after: () => {
      const btn = $('pub-copy-btn');
      if (!btn) return;
      btn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(state.pubApp?.redirect_uri || '');
          btn.textContent = 'Copied';
          setTimeout(() => { btn.textContent = 'Copy'; }, 1600);
        } catch {
          // Clipboard access is refused in some browsers and over plain http.
          // Selecting the text for them still gets the job done.
          const node = $('pub-redirect');
          const range = document.createRange();
          range.selectNodeContents(node);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          btn.textContent = 'Press Ctrl+C';
        }
      };
    },
  },
  {
    title: 'Paste them here',
    body: () => `
      <p>Google shows a client ID and a client secret once the client is
      created. Copy both across.</p>
      ${field('client_id', 'Client ID', 'input',
              state.pubApp?.client_id || '',
              'Ends in .apps.googleusercontent.com')}
      ${field('client_secret', 'Client secret', 'password',
              '', state.pubApp?.has_secret
              ? 'Already saved — leave blank to keep it'
              : 'Starts with GOCSPX-')}
      <p class="hint">Stored for your account only, and used solely to upload
      to the channel you connect next.</p>`,
    apply: async (form) => {
      const clientId = (form.client_id || '').trim();
      const secret = (form.client_secret || '').trim();
      if (!clientId) throw new Error('Paste the client ID from Google.');
      if (!secret && !state.pubApp?.has_secret) {
        throw new Error('Paste the client secret from Google.');
      }
      state.pubApp = await api('/api/youtube/app', {
        method: 'PUT',
        body: { client_id: clientId, client_secret: secret },
      });
    },
  },
];

let pubAt = 0;

/* Whether the tour is still waiting behind this. Set only on a first run, so
   somebody opening the walkthrough later is not shown the tour again. */
let pubThenTour = false;

function pubFinished() {
  $('pub').classList.add('hidden');
  if (pubThenTour) { pubThenTour = false; openTour(); }
}

async function openPublishing() {
  pubAt = 0;
  try {
    state.pubApp = await api('/api/youtube/app');
  } catch { state.pubApp = null; }
  $('pub').classList.remove('hidden');
  renderPublishing();
}

function renderPublishing() {
  const step = PUB_STEPS[pubAt];
  $('pub-step').textContent = `Step ${pubAt + 1} of ${PUB_STEPS.length}`;
  $('pub-title').textContent = step.title;
  $('pub-body').innerHTML = step.body();
  $('pub-dots').innerHTML = PUB_STEPS.map((_, i) =>
    `<i class="${i === pubAt ? 'on' : ''}"></i>`).join('');
  $('pub-back').disabled = pubAt === 0;
  $('pub-next').textContent =
    pubAt === PUB_STEPS.length - 1 ? 'Save and connect' : 'Next';
  // Only offered while nothing has been entered; past that point the way out
  // is to close the dialog, not to be told again that you could give up.
  $('pub-skip').classList.toggle('hidden', pubAt > 0);
  step.after?.();
}

function readPubForm() {
  const out = {};
  $('pub-body').querySelectorAll('[data-field]').forEach((input) => {
    out[input.dataset.field] = input.value;
  });
  return out;
}

$('pub-close').onclick = pubFinished;
$('pub').onclick = (e) => { if (e.target === $('pub')) $('pub-close').click(); };
$('pub-back').onclick = () => { pubAt -= 1; renderPublishing(); };

$('pub-skip').onclick = async () => {
  // A real choice, saved as one: publishing off, so nothing later claims a
  // video is on its way to a channel that was never connected.
  try {
    state.settings.auto_upload = false;
    const { settings } = await api('/api/studio/settings', {
      method: 'PUT', body: { settings: state.settings },
    });
    state.settings = settings;
    renderSettings();
    await loadStudio();
  } catch { /* the dialog closing matters more than the setting */ }
  pubFinished();
  toast('Videos will be made for you to download. You can turn on publishing '
        + 'any time from the Home screen.');
};

$('pub-next').onclick = async () => {
  const step = PUB_STEPS[pubAt];
  const button = $('pub-next');
  button.disabled = true;
  try {
    await step.apply?.(readPubForm());
    if (pubAt < PUB_STEPS.length - 1) {
      pubAt += 1;
      renderPublishing();
    } else {
      pubFinished();
      await loadStudio();
      toast('Saved. Now sign in with the Google account that owns your channel.');
      connectYouTube();
    }
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
  }
};

/* ------------------------------------------------------------- tour ---- */
/* An interactive walkthrough. Each step switches to the right screen and
   spotlights the real control, so people learn where things are rather than
   reading a description of them. `target` is a selector; omit it for a
   centred step with no highlight. */
const TOUR = [
  {
    title: 'Welcome to ClipForge',
    body: `<p>This makes short vertical videos and puts them on your channel.
      Here are the four things worth knowing &mdash; it takes about a minute.</p>`,
  },
  {
    tab: 'home',
    target: '#publish',
    title: 'This one button does everything',
    body: `<p>It finds the clips, cuts them into a countdown with a banner and
      a numbered list, writes the title and description, and uploads.</p>
      <p>Most days you will not touch anything else on this screen.</p>`,
  },
  {
    tab: 'home',
    target: '#dryrun',
    title: 'Not ready to publish?',
    body: `<p>A <b>dry run</b> does the whole thing but never uploads. The
      video lands in <b>History</b> for you to watch and download first.</p>`,
  },
  {
    tab: 'home',
    target: '#status-rows',
    title: 'This tells you what is missing',
    body: `<p>Anything that would stop a run shows up here. Connect your
      YouTube channel from this panel &mdash; after that, finished videos upload
      on their own.</p>
      <p>Your first uploads are <b>private</b>, so you get to watch them before
      anyone else can.</p>`,
  },
  {
    tab: 'home',
    target: '#automate-toggle',
    title: 'Or let it run without you',
    body: `<p>Switch this on, pick a time, and it publishes every day on our
      servers. Nothing needs to stay open on your machine.</p>
      <div class="callout">Daily automation is included with the paid plans.</div>`,
  },
  {
    tab: 'settings',
    target: '#open-presets',
    title: 'Start from a preset',
    body: `<p>Each preset is a different <b>shape</b> of video rather than a
      topic &mdash; a countdown, a fast meme cut, one specific TV show. Shape is
      what holds attention.</p>
      <p>Everything below is yours to change: 68 settings covering the cut, the
      on-screen text, the filters and the upload.</p>`,
  },
  {
    tab: 'activity',
    target: '#drop',
    title: 'Start by dropping in footage',
    body: `<p>Drop clips here. ClipForge cuts what you upload and sources
      nothing on your behalf, so the only rights involved are the ones you
      already hold.</p>
      <p>It is also the only way to cover sport, gaming, or anything recorded
      off a broadcast.</p>`,
  },
  {
    title: 'Last thing: it can say no',
    body: `<p>Every video is scored before it renders &mdash; how fast the
      opening gets going, whether a shot drags, how often it cuts, whether
      there is text on screen.</p>
      <p>Under 55 and it is <b>rejected</b>: you are told which rule failed and
      the run is refunded. A rejection is the tool working, not a failure.</p>
      <p>That's it. Press <b>Publish now</b> whenever you're ready.</p>`,
  },
];

let tourAt = 0;
let tourReturn = null;

function placeTour() {
  const step = TOUR[tourAt];
  const spot = $('tour-spot');
  const card = $('tour-card');
  const target = step.target ? document.querySelector(step.target) : null;

  if (!target) {
    spot.classList.add('no-target');
    card.classList.add('centred');
    card.style.top = '';
    card.style.left = '';
    return;
  }

  spot.classList.remove('no-target');
  card.classList.remove('centred');

  const pad = 8;
  const box = target.getBoundingClientRect();
  spot.style.top = `${box.top - pad}px`;
  spot.style.left = `${box.left - pad}px`;
  spot.style.width = `${box.width + pad * 2}px`;
  spot.style.height = `${box.height + pad * 2}px`;

  // Prefer sitting below the target, flip above when there is no room, and
  // keep the card fully on screen either way.
  const cardBox = card.getBoundingClientRect();
  const gap = 14;
  let top = box.bottom + gap;
  if (top + cardBox.height > window.innerHeight - 12) {
    top = box.top - cardBox.height - gap;
  }
  top = Math.min(Math.max(12, top), Math.max(12, window.innerHeight - cardBox.height - 12));

  let left = box.left + box.width / 2 - cardBox.width / 2;
  left = Math.min(Math.max(12, left), Math.max(12, window.innerWidth - cardBox.width - 12));

  card.style.top = `${top}px`;
  card.style.left = `${left}px`;
}

function renderTour() {
  const step = TOUR[tourAt];
  if (step.tab) showTab(step.tab);

  $('tour-step').textContent = `Step ${tourAt + 1} of ${TOUR.length}`;
  $('tour-title').textContent = step.title;
  $('tour-body').innerHTML = step.body;
  $('tour-dots').innerHTML = TOUR.map((_, i) =>
    `<i class="${i === tourAt ? 'on' : ''}"></i>`).join('');
  $('tour-back').disabled = tourAt === 0;
  $('tour-next').textContent = tourAt === TOUR.length - 1 ? 'Finish' : 'Next';

  // Bring the target into view first, then measure where it actually landed.
  const target = step.target ? document.querySelector(step.target) : null;
  if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
  placeTour();
  setTimeout(placeTour, target ? 340 : 0);
  $('tour-next').focus();
}

function openTour() {
  tourAt = 0;
  tourReturn = document.activeElement;
  $('tour').classList.remove('hidden');
  renderTour();
  document.addEventListener('keydown', tourKeys);
  window.addEventListener('resize', placeTour);
  window.addEventListener('scroll', placeTour, { passive: true });
}

async function closeTour() {
  $('tour').classList.add('hidden');
  document.removeEventListener('keydown', tourKeys);
  if (tourReturn && tourReturn.focus) tourReturn.focus();
  await api('/api/studio/onboarded?seen=true', { method: 'POST' }).catch(() => {});
}

function tourKeys(event) {
  if (event.key === 'Escape') { event.preventDefault(); closeTour(); }
  else if (event.key === 'ArrowRight') $('tour-next').click();
  else if (event.key === 'ArrowLeft' && tourAt > 0) $('tour-back').click();
  else if (event.key === 'Tab') {
    // Keep focus inside the dialog while it is open.
    const focusable = $('tour').querySelectorAll('button:not([disabled])');
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }
}

$('tour-next').onclick = () => {
  if (tourAt < TOUR.length - 1) { tourAt += 1; renderTour(); }
  else { closeTour(); showTab('settings'); toast('Start by loading a preset.'); }
};
$('tour-back').onclick = () => { if (tourAt > 0) { tourAt -= 1; renderTour(); } };
$('tour-skip').onclick = () => closeTour();
$('replay-tour').onclick = () => openTour();

/* ------------------------------------------------------------------ dots --
   The sign-in backdrop: a grid of squares that resolves outward from the
   centre, then keeps twinkling.

   The design this comes from runs it as a WebGL fragment shader through
   three.js and @react-three/fiber. That is a 3D engine and a renderer to fade
   in a grid of squares, so this is the same field drawn on a 2D canvas: the
   per-cell hash, the distance-based delay and the flicker are ported from the
   shader, the dependency is not.

   Stops itself when the gate is hidden, when the tab is in the background, and
   when the viewer prefers reduced motion, in which case it paints the settled
   state once and leaves it there. */
function startGateDots() {
  const canvas = document.getElementById('gate-dots');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');

  const SPACING = 20;          // grid pitch, matching u_total_size
  const DOT = 6;               // square size, matching u_dot_size
  const SPEED = 1.25;          // how fast the reveal sweeps outward
  const still = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let dpr = 1, cols = 0, rows = 0, cx = 0, cy = 0, started = 0, raf = 0;

  // The shader's random(): a cheap hash, stable per cell, so a dot keeps its
  // brightness and its delay between frames instead of boiling.
  function hash(x, y) {
    const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
    return n - Math.floor(n);
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(w / SPACING) + 1;
    rows = Math.ceil(h / SPACING) + 1;
    cx = cols / 2;
    cy = rows / 2;
  }

  function draw(elapsed, settled) {
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    ctx.fillStyle = '#ffffff';
    for (let i = 0; i < cols; i++) {
      for (let j = 0; j < rows; j++) {
        const seed = hash(i, j);
        // Distance sets when a cell arrives, the hash jitters it so the front
        // is ragged rather than a clean expanding ring.
        const delay = Math.hypot(i - cx, j - cy) * 0.03 + seed * 0.35;
        const age = elapsed * SPEED - delay;
        if (age <= 0) continue;

        // A slow per-cell flicker, the 2D reading of the shader's time-stepped
        // random pick. The settled frame skips it: a still image should not
        // inherit whatever phase the sine happened to be at.
        const flicker = settled
          ? 1
          : 0.55 + 0.45 * Math.sin(elapsed * 1.6 + seed * 42);
        const alpha = Math.min(1, age * 3) * (0.10 + seed * 0.34) * flicker;
        if (alpha <= 0.004) continue;
        ctx.globalAlpha = alpha;
        ctx.fillRect(i * SPACING, j * SPACING, DOT, DOT);
      }
    }
    ctx.globalAlpha = 1;
  }

  function frame(now) {
    if (!started) started = now;
    draw((now - started) / 1000);
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function run() {
    stop();
    // A hidden gate has no size, and drawing behind the app is wasted work.
    if (!canvas.clientWidth || !canvas.clientHeight) return;
    resize();
    if (still) { draw(999, true); return; }
    started = 0;
    raf = requestAnimationFrame(frame);
  }

  window.addEventListener('resize', run);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop(); else run();
  });

  // The gate is shown and hidden by toggling .hidden on it, which no event
  // reports. Watching the attribute keeps the canvas in step without the rest
  // of the app having to know it exists.
  const gate = document.getElementById('gate');
  if (gate && 'MutationObserver' in window) {
    new MutationObserver(function () {
      if (gate.classList.contains('hidden')) stop(); else run();
    }).observe(gate, { attributes: true, attributeFilter: ['class'] });
  }

  run();
}

/* ------------------------------------------------------------- boot ---- */
(async function boot() {
  startGateDots();
  state.pairCode = pairCodeFromUrl();
  if (state.pairCode) {
    // Shown on the sign-in screen, for the many people who land here logged
    // out and would otherwise wonder what the form has to do with the agent.
    $('gate-intent').textContent =
      'Sign in to pair the render agent on your computer.';
    $('gate-intent').classList.remove('hidden');
  }

  try {
    state.user = await api('/api/me');
    await enterApp();
  } catch { showGate(); }

  const billing = new URLSearchParams(location.search).get('billing');
  if (billing === 'success') {
    // Do not just say it worked. The webhook may not have arrived yet, or may
    // not be configured at all, and telling somebody their subscription is
    // active while the screen still says Free is worse than saying nothing.
    toast('Confirming your subscription…');
    try {
      const { plan } = await api('/api/billing/sync', { method: 'POST' });
      await loadPlans();
      toast(plan && plan !== 'free'
        ? `You are on ${plan}.`
        : 'Payment received. Your plan will update shortly.');
    } catch {
      toast('Payment received. Your plan will update shortly.');
    }
    history.replaceState({}, '', '/app');
  } else if (billing === 'cancelled') {
    toast('Checkout cancelled. Nothing was charged.');
    history.replaceState({}, '', '/app');
  }
  window.addEventListener('message', (e) => {
    if (e.data === 'clipforge-youtube') loadStudio();
  });
})();
