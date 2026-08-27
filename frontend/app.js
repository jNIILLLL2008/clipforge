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
    $('auth-submit').textContent = authMode === 'login' ? 'Sign in' : 'Create account';
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

  // Resume a purchase started from the landing page before anything else.
  if (state.pendingPlan) {
    const plan = state.pendingPlan;
    state.pendingPlan = null;
    history.replaceState({}, '', '/app');
    await startCheckout(plan);
    return;
  }
  if (state.studio && !state.studio.onboarded) openTour();
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
  if (name === 'activity') { loadUploads(); loadSources(); loadPlans(); }
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
      ? '<button class="linkish" id="connect-youtube">Connect</button>' : '';
    return `<div class="row">
      <span class="row-label">${esc(row.label)}
        ${row.detail ? `<span class="row-sub">${esc(row.detail)} ${connect}</span>` : ''}</span>
      <span class="pill${pill}">${text}</span>
    </div>`;
  }).join('');

  const connectBtn = $('connect-youtube');
  if (connectBtn) connectBtn.onclick = connectYouTube;

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
    return `<div class="row stacked"><span class="row-label">${esc(field.label)}</span>
      <textarea class="row-input" id="${id}" data-key="${field.key}"
        placeholder="one per line">${esc((value || []).join('\n'))}</textarea></div>`;
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
    };
    if (input.type === 'checkbox' || input.tagName === 'SELECT') input.onchange = input.oninput;
  });
}

$('settings-save').onclick = async () => {
  $('settings-save').disabled = true;
  try {
    const { settings } = await api('/api/studio/settings', {
      method: 'PUT', body: { settings: state.settings },
    });
    state.settings = settings;
    state.dirty = false;
    renderSettings();
    await loadStudio();
    $('settings-status').textContent = 'Saved';
    toast('Settings saved.');
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
      ${job.error ? `<p class="error">${esc(job.error)}</p>` : ''}
      ${job.upload_error ? `<p class="error">Upload: ${esc(job.upload_error)}</p>` : ''}
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
    title: 'Your own footage always works',
    body: `<p>Drop clips here. Footage you own has nothing to claim, and it is
      the only way to cover what stock libraries do not &mdash; sport, gaming,
      anything recorded off a broadcast.</p>
      <p>Under this you can see every source and whether it is ready to use.</p>`,
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

/* ------------------------------------------------------------- boot ---- */
(async function boot() {
  try {
    state.user = await api('/api/me');
    await enterApp();
  } catch { showGate(); }

  if (new URLSearchParams(location.search).get('billing') === 'success') {
    toast('Subscription active.');
    history.replaceState({}, '', '/');
  }
  window.addEventListener('message', (e) => {
    if (e.data === 'clipforge-youtube') loadStudio();
  });
})();
