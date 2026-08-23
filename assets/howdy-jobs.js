/* Howdy Jobs — shared front-end helpers (no build step, no dependencies). */
(function () {
  'use strict';

  /* ── theme ────────────────────────────────────────────────────────────── */
  var saved = null;
  try { saved = localStorage.getItem('howdy-theme'); } catch (e) {}
  document.documentElement.setAttribute('data-theme', saved || 'dark');

  function toggleTheme() {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('howdy-theme', next); } catch (e) {}
  }

  /* ── api ──────────────────────────────────────────────────────────────── */
  async function api(path, options) {
    var opts = options || {};
    var headers = { 'X-Howdy-Client': 'web' };
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';

    var res = await fetch(path, {
      method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
      headers: headers,
      credentials: 'same-origin',
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined
    });

    var data = {};
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
    return data;
  }

  /* ── dom helpers ──────────────────────────────────────────────────────── */
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  function esc(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var toastTimer;
  function toast(message, kind) {
    var el = $('#toast');
    if (!el) return;
    el.textContent = message;
    el.className = 'toast show ' + (kind || '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.className = 'toast ' + (kind || ''); }, 4200);
  }

  function openModal(id) {
    var el = document.getElementById(id);
    if (el) { el.classList.add('open'); document.body.style.overflow = 'hidden'; }
  }
  function closeModal(id) {
    var el = document.getElementById(id);
    if (el) { el.classList.remove('open'); document.body.style.overflow = ''; }
  }
  document.addEventListener('click', function (e) {
    if (e.target.classList && e.target.classList.contains('modal')) {
      e.target.classList.remove('open');
      document.body.style.overflow = '';
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      $$('.modal.open').forEach(function (m) { m.classList.remove('open'); });
      document.body.style.overflow = '';
    }
  });

  function timeAgo(iso) {
    var mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 60) return mins <= 1 ? 'just now' : mins + ' min ago';
    var hours = Math.floor(mins / 60);
    if (hours < 24) return hours + 'h ago';
    var days = Math.floor(hours / 24);
    if (days < 30) return days + 'd ago';
    return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' });
  }

  var money = function (n) { return '$' + Number(n).toFixed(2); };

  /* ── session ──────────────────────────────────────────────────────────── */
  var config = null;
  var user = null;

  async function loadConfig() {
    if (!config) config = await api('/api/jobs-config');
    return config;
  }

  async function loadUser() {
    try {
      var data = await api('/api/auth?action=me');
      user = data.user;
    } catch (e) {
      user = null;
    }
    return user;
  }

  async function signOut() {
    await api('/api/auth?action=logout', { body: {} });
    user = null;
  }

  /**
   * Renders the Google Identity button when GOOGLE_CLIENT_ID is configured on
   * the server; otherwise the email form is the only path (and we say so).
   */
  function mountGoogle(containerId, role, onDone) {
    var host = document.getElementById(containerId);
    if (!host) return;
    if (!config || !config.googleClientId) {
      host.innerHTML = '<p class="hint">Google sign-in activates once GOOGLE_CLIENT_ID is set on the server. '
        + 'Use email and password below.</p>';
      return;
    }
    var script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = function () {
      window.google.accounts.id.initialize({
        client_id: config.googleClientId,
        callback: async function (response) {
          try {
            var data = await api('/api/auth?action=google', {
              body: { credential: response.credential, role: role() }
            });
            user = data.user;
            onDone(user);
          } catch (err) {
            toast(err.message, 'err');
          }
        }
      });
      window.google.accounts.id.renderButton(host, {
        theme: 'filled_black', size: 'large', width: 320, text: 'continue_with'
      });
    };
    script.onerror = function () {
      host.innerHTML = '<p class="hint">Google sign-in could not load. Use email and password below.</p>';
    };
    document.head.appendChild(script);
  }

  window.Howdy = {
    api: api, $: $, $$: $$, esc: esc, toast: toast,
    openModal: openModal, closeModal: closeModal,
    timeAgo: timeAgo, money: money, toggleTheme: toggleTheme,
    loadConfig: loadConfig, loadUser: loadUser, signOut: signOut, mountGoogle: mountGoogle,
    get user() { return user; },
    set user(value) { user = value; },
    get config() { return config; }
  };
})();
