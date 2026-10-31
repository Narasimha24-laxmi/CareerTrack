/* CareerTrack front end: plain JavaScript, no libraries.
 * Every piece of user text is inserted with textContent / text nodes (never innerHTML),
 * so company names, notes or resume text can never run as code (no XSS).
 */
(() => {
  'use strict';

  const STATUSES = ['Applied', 'Interview', 'Offer', 'Rejected'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const MAX_RESUME_BYTES = 2 * 1024 * 1024;
  const SVG_NS = 'http://www.w3.org/2000/svg';

  const root = document.getElementById('app');
  const toastBox = document.getElementById('toasts');
  const state = { user: null, view: 'dashboard', applications: [], reminders: null, stats: null, filter: '' };
  // Functions that repaint the dashboard sections (set while the dashboard is on screen).
  let dashboard = null;

  // ------------------------------------------------------------------ helpers
  function h(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (value === true) node.setAttribute(key, '');
      else node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  // Like node.replaceChildren(), but skips null/false. The native method would print the word "null".
  function fill(node, ...children) {
    node.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
    return node;
  }

  function svg(tag, attrs, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    node.append(...children);
    return node;
  }

  function localToday() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function fmtDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : '';
  }

  function toast(message, kind = 'info') {
    const node = h('div', { class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status', text: message });
    while (toastBox.children.length >= 3) toastBox.firstChild.remove(); // keep at most 3 on screen
    toastBox.append(node);
    setTimeout(() => node.remove(), kind === 'error' ? 7000 : 4000);
  }

  class ApiError extends Error {
    constructor(message, status, field) {
      super(message);
      this.status = status;
      this.field = field;
    }
  }

  async function api(method, url, body) {
    const options = { method, headers: { 'X-Requested-With': 'CareerTrack' }, credentials: 'same-origin' };
    if (body instanceof FormData) {
      options.body = body;
    } else if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(url, options);
    } catch (_) {
      throw new ApiError("Can't reach the server. Check your internet connection and try again.", 0);
    }
    let data = null;
    try {
      data = await response.json();
    } catch (_) { /* non-JSON reply */ }
    if (!response.ok) {
      const quiet = /\/api\/(login|register|me|logout)$/.test(url);
      if (response.status === 401 && state.user && !quiet) sessionExpired();
      const fallback = response.status >= 500
        ? 'Something went wrong on our side. Please try again in a moment.'
        : 'Something went wrong. Please try again.';
      throw new ApiError((data && data.error) || fallback, response.status, data && data.field);
    }
    return data;
  }

  function sessionExpired() {
    state.user = null;
    dashboard = null;
    renderAuth('login');
    toast('Your session expired. Please log in again.', 'error');
  }

  // ------------------------------------------------------------------ form helpers
  function field({ id, label, type = 'text', value = '', hint, options, rows, ...attrs }) {
    let input;
    if (options) {
      input = h('select', { id, name: id },
        options.map((o) => h('option', { value: o, text: o, selected: o === value })));
    } else if (rows) {
      input = h('textarea', { id, name: id, rows, ...attrs });
      input.value = value;
    } else {
      input = h('input', { id, name: id, type, ...attrs });
      input.value = value;
    }
    const error = h('p', { class: 'field-error', id: `${id}-error`, hidden: true });
    input.setAttribute('aria-describedby', `${id}-error`);
    const wrap = h('div', { class: 'field' },
      h('label', { for: id, text: label }),
      hint ? h('p', { class: 'hint', text: hint }) : null,
      input, error);
    return { wrap, input, error };
  }

  function setFieldError(f, message) {
    f.error.textContent = message;
    f.error.hidden = false;
    f.wrap.classList.add('invalid');
    f.input.setAttribute('aria-invalid', 'true');
  }

  function clearErrors(form, fields, box) {
    Object.values(fields).forEach((f) => {
      f.error.hidden = true;
      f.wrap.classList.remove('invalid');
      f.input.removeAttribute('aria-invalid');
    });
    box.hidden = true;
  }

  // Show the server's message next to the field it names, or at the top of the form.
  function showFormError(err, fields, box) {
    const target = err.field && fields[err.field];
    if (target) {
      setFieldError(target, err.message);
      target.input.focus();
    } else {
      box.textContent = err.message;
      box.hidden = false;
    }
  }

  async function submitting(button, busyText, work) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = busyText;
    try {
      return await work();
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function openDialog(dialog) {
    document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove());
    dialog.showModal();
  }

  // ------------------------------------------------------------------ auth screen
  function renderAuth(mode = 'login') {
    const isLogin = mode === 'login';
    const fields = {
      email: field({ id: 'auth-email', label: 'Email', type: 'email', autocomplete: 'email', maxlength: 254 }),
      password: field({
        id: 'auth-password', label: 'Password', type: 'password', maxlength: 128,
        autocomplete: isLogin ? 'current-password' : 'new-password',
        hint: isLogin ? null : 'At least 8 characters.',
      }),
    };
    const errorBox = h('div', { class: 'form-error', role: 'alert', hidden: true });
    const submit = h('button', { class: 'btn btn-primary', type: 'submit', text: isLogin ? 'Log in' : 'Create account' });

    const form = h('form', {
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        clearErrors(form, fields, errorBox);
        try {
          const data = await submitting(submit, isLogin ? 'Logging in...' : 'Creating account...', () =>
            api('POST', isLogin ? '/api/login' : '/api/register', {
              email: fields.email.input.value,
              password: fields.password.input.value,
            }));
          state.user = data.user;
          state.view = 'dashboard';
          render();
        } catch (err) {
          // The server uses one generic message for wrong login, so show it at the top.
          if (isLogin && err.status === 401) { errorBox.textContent = err.message; errorBox.hidden = false; }
          else showFormError(err, fields, errorBox);
        }
      },
    }, errorBox, fields.email.wrap, fields.password.wrap, submit);
    submit.classList.add('btn-block');

    const tab = (label, tabMode) => h('button', {
      type: 'button', role: 'tab', 'aria-selected': String(mode === tabMode), text: label,
      onclick: () => renderAuth(tabMode),
    });

    root.replaceChildren(h('div', { class: 'auth-wrap' }, h('main', { class: 'auth-card' },
      h('div', { class: 'brand' }, logo(), 'CareerTrack'),
      h('p', { class: 'tagline', text: 'Track every application, never miss a deadline, and see how your resume matches the job.' }),
      h('div', { class: 'tabs', role: 'tablist' }, tab('Log in', 'login'), tab('Create account', 'register')),
      form)));
    fields.email.input.focus();
  }

  function logo() {
    return svg('svg', { width: 28, height: 28, viewBox: '0 0 32 32', 'aria-hidden': 'true' },
      svg('rect', { width: 32, height: 32, rx: 8, fill: '#1B4F72' }),
      svg('rect', { x: 6, y: 8, width: 5, height: 16, rx: 2, fill: '#fff' }),
      svg('rect', { x: 13.5, y: 8, width: 5, height: 11, rx: 2, fill: '#fff', opacity: '.85' }),
      svg('rect', { x: 21, y: 8, width: 5, height: 6, rx: 2, fill: '#fff', opacity: '.7' }));
  }

  // ------------------------------------------------------------------ shell
  function render() {
    dashboard = null;
    if (!state.user) { renderAuth('login'); return; }
    const nav = (label, view) => h('button', {
      type: 'button', text: label, 'aria-current': state.view === view ? 'page' : null,
      onclick: () => { state.view = view; render(); },
    });
    const logout = h('button', { class: 'btn btn-small', type: 'button', text: 'Log out', onclick: async () => {
      try { await api('POST', '/api/logout'); } catch (_) { /* leaving anyway */ }
      state.user = null; state.applications = []; state.reminders = null; state.stats = null;
      render();
    } });
    const topbar = h('header', { class: 'topbar' }, h('div', { class: 'topbar-inner' },
      h('div', { class: 'brand' }, logo(), 'CareerTrack'),
      h('nav', { class: 'nav', 'aria-label': 'Main' }, nav('Dashboard', 'dashboard'), nav('Resume matcher', 'matcher')),
      h('div', { class: 'user-box' }, h('span', { class: 'user-email', title: state.user.email, text: state.user.email }), logout)));
    root.replaceChildren(topbar, state.view === 'matcher' ? matcherPage() : dashboardPage());
    if (state.view === 'dashboard') loadData(true);
  }

  // ------------------------------------------------------------------ dashboard
  function dashboardPage() {
    const remindersHost = h('div');
    const statsHost = h('div');
    const boardHost = h('div');
    const search = h('input', {
      type: 'search', placeholder: 'Search company or role', 'aria-label': 'Search applications',
      class: 'search', value: state.filter,
      oninput: (e) => { state.filter = e.target.value; renderBoard(); },
    });

    function renderReminders() {
      const data = state.reminders;
      if (!data) { remindersHost.replaceChildren(h('p', { class: 'empty-note', text: 'Loading reminders...' })); return; }
      const groups = [
        ['overdue', 'Overdue'], ['today', 'Due today'], ['upcoming', 'Upcoming (next 7 days)'],
      ].map(([bucket, title]) => {
        const items = data.items.filter((i) => i.bucket === bucket);
        if (!items.length) return null;
        return h('section', { class: `reminder-group group-${bucket}` },
          h('h3', {}, title, h('span', { class: 'count-dot', text: items.length })),
          h('ul', {}, items.map((item) => h('li', {}, h('button', {
            type: 'button', class: 'reminder-item', onclick: () => editById(item.application_id),
          },
            h('strong', { text: item.company }),
            h('span', { text: `${item.role}` }),
            h('small', { text: `${item.kind}: ${fmtDate(item.date)} - ${item.label}` }))))));
      }).filter(Boolean);
      const nodes = groups.length ? [h('div', { class: 'reminder-groups' }, groups)] : [
        h('p', { class: 'empty-note', text: state.applications.length
          ? 'Nothing is due in the next 7 days.'
          : 'Add an application with a deadline or interview date and it will show up here.' })];
      if (data.counts.later) {
        nodes.push(h('p', { class: 'muted small-note',
          text: `${data.counts.later} more ${data.counts.later === 1 ? 'date is' : 'dates are'} more than 7 days away.` }));
      }
      remindersHost.replaceChildren(...nodes);
    }

    function renderStats() {
      const s = state.stats;
      if (!s) { statsHost.replaceChildren(h('p', { class: 'empty-note', text: 'Loading stats...' })); return; }
      const stat = (label, value) => h('div', { class: 'stat' }, h('dt', { text: label }), h('dd', { text: value }));
      statsHost.replaceChildren(h('dl', { class: 'stats' },
        stat('Total applications', s.total),
        ...STATUSES.map((name) => stat(name, s.by_status[name])),
        stat('Response rate', `${s.response_rate}%`),
        h('p', { class: 'stat-note', text: 'Response rate is the share of applications that moved past Applied.' })));
    }

    function renderBoard() {
      const query = state.filter.trim().toLowerCase();
      const visible = state.applications.filter((a) =>
        !query || a.company.toLowerCase().includes(query) || a.role.toLowerCase().includes(query));
      if (!state.applications.length) {
        boardHost.replaceChildren(h('div', { class: 'board-empty' },
          h('p', { text: "You haven't added any applications yet." }),
          h('button', { class: 'btn btn-primary', type: 'button', text: 'Add your first application', onclick: () => openApplicationForm() })));
        return;
      }
      boardHost.replaceChildren(h('div', { class: 'board' }, STATUSES.map((status) => {
        const cards = visible.filter((a) => a.status === status);
        const body = h('div', { class: 'column-body', 'data-status': status },
          cards.length ? cards.map(applicationCard) : h('p', { class: 'column-empty', text: query ? 'No matches' : 'Nothing here yet' }));
        body.addEventListener('dragover', (e) => { e.preventDefault(); body.classList.add('drop-target'); });
        body.addEventListener('dragleave', (e) => { if (!body.contains(e.relatedTarget)) body.classList.remove('drop-target'); });
        body.addEventListener('drop', (e) => {
          e.preventDefault();
          body.classList.remove('drop-target');
          const id = Number(e.dataTransfer.getData('text/plain'));
          const found = state.applications.find((a) => a.id === id);
          if (found && found.status !== status) moveStatus(found, status);
        });
        return h('section', { class: 'column', 'data-status': status, 'aria-label': `${status} applications` },
          h('div', { class: 'column-head' }, h('h3', { text: status }), h('span', { class: 'column-count', text: cards.length })),
          body);
      })));
    }

    dashboard = { renderReminders, renderStats, renderBoard };
    renderReminders(); renderStats(); renderBoard();

    return h('main', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', {}, h('h1', { text: 'Dashboard' }), h('p', { text: 'Your applications, deadlines and progress in one place.' })),
        h('button', { class: 'btn btn-primary', type: 'button', text: 'Add application', onclick: () => openApplicationForm() })),
      h('section', { class: 'panel', 'aria-labelledby': 'rem-title' },
        h('div', { class: 'panel-head' }, h('h2', { id: 'rem-title', text: 'Reminders' })), remindersHost),
      h('section', { class: 'panel', 'aria-label': 'Statistics' }, statsHost),
      h('section', { 'aria-labelledby': 'board-title' },
        h('div', { class: 'panel-head' }, h('h2', { id: 'board-title', text: 'Applications' }), search),
        boardHost));
  }

  async function loadData(first = false) {
    const today = localToday();
    try {
      const [apps, reminders, stats] = await Promise.all([
        api('GET', '/api/applications'),
        api('GET', `/api/reminders?today=${today}`),
        api('GET', '/api/stats'),
      ]);
      state.applications = apps.applications;
      state.reminders = reminders;
      state.stats = stats;
    } catch (err) {
      if (err.status === 401) return;
      toast(err.message, 'error');
      // On the first load, also leave a visible "Try again" button on the page.
      const page = document.querySelector('.page');
      if (first && dashboard && page && !page.querySelector('.load-error')) {
        page.append(h('div', { class: 'panel load-error' },
          h('p', { text: 'We could not load your applications.' }),
          h('button', { class: 'btn', type: 'button', text: 'Try again', onclick: () => loadData(true) })));
      }
      return;
    }
    document.querySelector('.load-error')?.remove();
    if (dashboard) { dashboard.renderReminders(); dashboard.renderStats(); dashboard.renderBoard(); }
  }

  function reminderFor(app, kind) {
    if (!state.reminders) return null;
    return state.reminders.items.find((i) => i.application_id === app.id && i.kind === kind) || null;
  }

  function dateLine(app, kind, iso) {
    if (!iso) return null;
    const reminder = reminderFor(app, kind);
    return h('div', { class: 'card-date' },
      h('span', { class: 'label', text: `${kind}:` }),
      h('span', { text: fmtDate(iso) }),
      reminder ? h('span', { class: `pill pill-${reminder.bucket}`, text: reminder.label }) : null);
  }

  function applicationCard(app) {
    const card = h('article', { class: 'card', draggable: 'true', 'aria-label': `${app.company}, ${app.role}` });
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', String(app.id));
      e.dataTransfer.effectAllowed = 'move';
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));

    const moveSelect = h('select', {
      'aria-label': `Change status of ${app.company}`,
      onchange: (e) => moveStatus(app, e.target.value),
    }, STATUSES.map((s) => h('option', { value: s, text: s, selected: s === app.status })));

    fill(card,
      h('h4', { text: app.company }),
      h('p', { class: 'role', text: app.role }),
      app.applied_date ? h('div', { class: 'card-date' }, h('span', { class: 'label', text: 'Applied:' }), h('span', { text: fmtDate(app.applied_date) })) : null,
      dateLine(app, 'Deadline', app.deadline),
      dateLine(app, 'Interview', app.interview_date),
      app.notes ? h('p', { class: 'notes', text: app.notes }) : null,
      /^https?:\/\//i.test(app.job_link)
        ? h('a', { class: 'card-link', href: app.job_link, target: '_blank', rel: 'noopener noreferrer', text: 'Open job posting' })
        : null,
      h('div', { class: 'card-actions' }, moveSelect, h('span', { class: 'spacer' }),
        h('button', { class: 'btn btn-small', type: 'button', text: 'Edit', onclick: () => openApplicationForm(app) }),
        h('button', { class: 'btn btn-small', type: 'button', text: 'Delete', onclick: () => confirmDelete(app) })));
    return card;
  }

  function editById(id) {
    const found = state.applications.find((a) => a.id === id);
    if (found) openApplicationForm(found);
  }

  async function moveStatus(app, status) {
    try {
      await api('PATCH', `/api/applications/${app.id}/status`, { status });
      toast(`Moved ${app.company} to ${status}.`, 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
    await loadData();
  }

  // ------------------------------------------------------------------ add / edit dialog
  function openApplicationForm(existing) {
    const a = existing || {};
    const fields = {
      company: field({ id: 'company', label: 'Company', value: a.company || '', maxlength: 100, autocomplete: 'off' }),
      role: field({ id: 'role', label: 'Role', value: a.role || '', maxlength: 100, autocomplete: 'off' }),
      job_link: field({ id: 'job_link', label: 'Job link (optional)', type: 'url', value: a.job_link || '', maxlength: 500, placeholder: 'https://company.com/jobs/123' }),
      status: field({ id: 'status', label: 'Status', value: a.status || 'Applied', options: STATUSES }),
      applied_date: field({ id: 'applied_date', label: 'Applied on', type: 'date', value: existing ? a.applied_date || '' : localToday() }),
      deadline: field({ id: 'deadline', label: 'Deadline', type: 'date', value: a.deadline || '' }),
      interview_date: field({ id: 'interview_date', label: 'Interview date', type: 'date', value: a.interview_date || '' }),
      notes: field({ id: 'notes', label: 'Notes (optional)', value: a.notes || '', rows: 3, maxlength: 2000 }),
    };
    const errorBox = h('div', { class: 'form-error', role: 'alert', hidden: true });
    const save = h('button', { class: 'btn btn-primary', type: 'submit', text: 'Save application' });
    const dialog = h('dialog', { class: 'modal', 'aria-labelledby': 'form-title' });

    const form = h('form', {
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        clearErrors(form, fields, errorBox);
        const body = {};
        Object.entries(fields).forEach(([key, f]) => { body[key] = f.input.value; });
        try {
          await submitting(save, 'Saving...', () => existing
            ? api('PUT', `/api/applications/${existing.id}`, body)
            : api('POST', '/api/applications', body));
          dialog.close();
          toast(existing ? 'Application updated.' : 'Application added.', 'success');
          await loadData();
        } catch (err) {
          showFormError(err, fields, errorBox);
        }
      },
    },
    errorBox,
    fields.company.wrap, fields.role.wrap, fields.job_link.wrap, fields.status.wrap,
    h('div', { class: 'form-row' }, fields.applied_date.wrap, fields.deadline.wrap, fields.interview_date.wrap),
    fields.notes.wrap,
    h('div', { class: 'modal-actions' },
      h('button', { class: 'btn', type: 'button', text: 'Cancel', onclick: () => dialog.close() }), save));

    dialog.append(h('div', { class: 'modal-inner' },
      h('h2', { id: 'form-title', text: existing ? 'Edit application' : 'Add application' }), form));
    openDialog(dialog);
  }

  function confirmDelete(app) {
    const dialog = h('dialog', { class: 'modal', 'aria-labelledby': 'del-title' });
    const del = h('button', { class: 'btn btn-danger', type: 'button', text: 'Delete application' });
    del.addEventListener('click', async () => {
      try {
        await submitting(del, 'Deleting...', () => api('DELETE', `/api/applications/${app.id}`));
        dialog.close();
        toast('Application deleted.', 'success');
        await loadData();
      } catch (err) {
        dialog.close();
        toast(err.message, 'error');
        await loadData();
      }
    });
    dialog.append(h('div', { class: 'modal-inner' },
      h('h2', { id: 'del-title', text: 'Delete this application?' }),
      h('p', { class: 'confirm-text', text: `${app.role} at ${app.company} will be removed permanently.` }),
      h('div', { class: 'modal-actions' },
        h('button', { class: 'btn', type: 'button', text: 'Keep it', onclick: () => dialog.close() }), del)));
    openDialog(dialog);
  }

  // ------------------------------------------------------------------ resume matcher
  function matcherPage() {
    const resultHost = h('section', { class: 'panel', 'aria-live': 'polite' },
      h('p', { class: 'placeholder-result', text: 'Your match score will appear here.' }));

    const fileInput = h('input', { id: 'resume_file', name: 'resume_file', type: 'file', accept: '.pdf,.docx,.txt' });
    const fileError = h('p', { class: 'field-error', id: 'resume_file-error', hidden: true });
    fileInput.setAttribute('aria-describedby', 'resume_file-error');
    const fileField = { wrap: h('div', { class: 'field' },
      h('label', { for: 'resume_file', text: 'Upload your resume' }),
      h('p', { class: 'hint', text: 'PDF, DOCX or TXT, up to 2 MB. The file is read in memory and is not stored.' }),
      h('div', { class: 'file-drop' }, fileInput,
        h('button', { class: 'btn-link', type: 'button', text: 'Clear file', onclick: () => { fileInput.value = ''; } })),
      fileError), input: fileInput, error: fileError };

    const resume = field({ id: 'resume_text', label: 'Paste your resume text', rows: 7, placeholder: 'Skills: React, Node.js, SQL ...' });
    const job = field({ id: 'job_description', label: 'Job description', rows: 9, placeholder: 'Paste the full job posting here.' });
    const fields = { resume_file: fileField, resume_text: resume, job_description: job };
    const errorBox = h('div', { class: 'form-error', role: 'alert', hidden: true });
    const submit = h('button', { class: 'btn btn-primary', type: 'submit', text: 'Check match' });

    const form = h('form', {
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        clearErrors(form, fields, errorBox);
        const file = fileInput.files[0];
        if (file) {
          if (!/\.(pdf|docx|txt)$/i.test(file.name)) {
            return showFormError({ field: 'resume_file', message: 'Unsupported file type. Please upload a PDF, DOCX or TXT file.' }, fields, errorBox);
          }
          if (file.size > MAX_RESUME_BYTES) {
            return showFormError({ field: 'resume_file', message: 'That file is too large. Resume files must be 2 MB or smaller.' }, fields, errorBox);
          }
        }
        const data = new FormData();
        data.append('job_description', job.input.value);
        if (file) data.append('resume_file', file); else data.append('resume_text', resume.input.value);
        try {
          const result = await submitting(submit, 'Checking...', () => api('POST', '/api/match', data));
          renderResult(resultHost, result);
        } catch (err) {
          showFormError(err, fields, errorBox);
        }
      },
    }, errorBox, fileField.wrap, h('div', { class: 'or-divider', text: 'or' }), resume.wrap, job.wrap, submit);

    return h('main', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', {},
        h('h1', { text: 'Resume matcher' }),
        h('p', { text: 'See which skills a job asks for and which ones your resume is missing.' }))),
      h('div', { class: 'matcher' }, h('section', { class: 'panel' }, form), resultHost));
  }

  function renderResult(host, r) {
    const pct = r.match_percent;
    const tone = pct >= 70 ? 'good' : pct >= 40 ? 'fair' : 'poor';
    const headline = pct >= 70 ? 'Strong match' : pct >= 40 ? 'Partial match' : 'Weak match';
    const circumference = 2 * Math.PI * 60;
    const bar = svg('circle', { class: 'bar', cx: 70, cy: 70, r: 60, 'stroke-dasharray': circumference.toFixed(2) });
    bar.style.strokeDashoffset = circumference;
    requestAnimationFrame(() => requestAnimationFrame(() => { bar.style.strokeDashoffset = circumference * (1 - pct / 100); }));

    const ring = h('div', { class: `ring ${tone}`, role: 'img', 'aria-label': `${pct} percent match` },
      svg('svg', { width: 140, height: 140, viewBox: '0 0 140 140', 'aria-hidden': 'true' },
        svg('circle', { class: 'track', cx: 70, cy: 70, r: 60 }), bar),
      h('div', { class: 'ring-label' }, h('strong', { text: `${pct}%` }), h('span', { text: 'match' })));

    const chips = (title, list, cls, emptyText) => h('div', { class: 'chip-block' },
      h('h4', {}, title, h('span', { class: 'muted', text: `(${list.length})` })),
      list.length ? h('ul', { class: 'chips' }, list.map((s) => h('li', { class: `chip ${cls}`, text: s }))) : h('p', { class: 'muted', text: emptyText }));

    fill(host,
      h('div', { class: 'result-top' }, ring, h('div', { class: 'result-summary' },
        h('h3', { text: headline }),
        h('p', { text: `Your resume covers ${r.matched_skills.length} of the ${r.job_skill_count} skills this job asks for.` }),
        h('p', { text: `Resume source: ${r.resume_source}.` }))),
      r.warning ? h('p', { class: 'result-warning', role: 'alert', text: r.warning }) : null,
      chips('Skills you have', r.matched_skills, 'chip-have', 'None of the required skills were found in your resume.'),
      chips('Skills to add', r.missing_skills, 'chip-miss', 'Nothing is missing. Your resume covers every skill in this job.'),
      r.missing_skills.length ? h('p', { class: 'muted small-note tip', text: 'Add a missing skill only if you really have it, ideally with a project or experience that shows it.' }) : null,
      chips('Other skills on your resume', r.extra_skills, 'chip-extra', 'No other skills found.'),
      h('details', { class: 'preview' },
        h('summary', { text: 'What we read from your resume' }),
        h('pre', { text: r.resume_preview + (r.resume_chars > r.resume_preview.length ? ' ...' : '') })));
  }

  // ------------------------------------------------------------------ start
  async function boot() {
    try {
      const data = await api('GET', '/api/me');
      state.user = data.user;
      render();
    } catch (err) {
      if (err.status === 401) { renderAuth('login'); return; }
      root.replaceChildren(h('div', { class: 'boot' },
        h('p', { text: err.message }),
        h('button', { class: 'btn', type: 'button', text: 'Try again', onclick: boot })));
    }
  }

  boot();
})();
