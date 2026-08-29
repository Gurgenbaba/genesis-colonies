(() => {
  'use strict';

  const state = { payload: null, mode: 'player', query: '', loading: false };

  function dialog() { return document.querySelector('[data-gc-changelog-dialog]'); }
  function list() { const root = dialog(); return root ? root.querySelector('[data-gc-changelog-list]') : null; }
  function status() { const root = dialog(); return root ? root.querySelector('[data-gc-changelog-status]') : null; }
  function meta() { const root = dialog(); return root ? root.querySelector('[data-gc-changelog-meta]') : null; }

  function normalize(text) { return String(text || '').toLowerCase(); }

  function matches(entry) {
    if (state.mode !== 'all' && entry.technical) return false;
    const q = normalize(state.query).trim();
    if (!q) return true;
    return [entry.title, entry.detail, entry.category, entry.area, entry.date, entry.sha, entry.milestone]
      .some((part) => normalize(part).includes(q));
  }

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = String(text);
    return el;
  }

  function render() {
    const root = dialog();
    const target = list();
    if (!root || !target || !state.payload) return;
    target.replaceChildren();

    let visible = 0;
    let opened = 0;
    (state.payload.groups || []).forEach((group) => {
      const entries = (group.entries || []).filter(matches);
      if (!entries.length) return;
      visible += entries.length;

      const details = node('details', 'gc-player-changelog-day');
      if (opened < 3) details.open = true;
      opened += 1;
      const summary = node('summary', 'gc-player-changelog-day-head');
      summary.append(node('span', 'gc-player-changelog-date', group.label || group.date || 'Unknown date'));
      summary.append(node('span', 'gc-player-changelog-day-count gc-mono', `${entries.length}`));
      details.append(summary);

      const body = node('div', 'gc-player-changelog-day-body');
      entries.forEach((entry) => {
        const article = node('article', `gc-player-changelog-entry${entry.technical ? ' is-technical' : ''}`);
        const top = node('div', 'gc-player-changelog-entry-top');
        top.append(node('span', 'gc-player-changelog-category', entry.category || 'Update'));
        if (entry.area) top.append(node('span', 'gc-player-changelog-area', entry.area));
        if (entry.technical) top.append(node('span', 'gc-player-changelog-technical', 'TECH'));
        article.append(top);
        article.append(node('h3', 'gc-player-changelog-entry-title', entry.title || 'Update'));
        if (entry.detail) article.append(node('p', 'gc-player-changelog-entry-detail', entry.detail));
        if (entry.sha || entry.url) {
          const source = node('div', 'gc-player-changelog-source gc-mono');
          if (entry.url) {
            const link = node('a', '', entry.sha ? `source ${entry.sha}` : 'source');
            link.href = entry.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            source.append(link);
          } else if (entry.sha) {
            source.textContent = entry.sha;
          }
          article.append(source);
        }
        body.append(article);
      });
      details.append(body);
      target.append(details);
    });

    const stat = status();
    if (stat) {
      stat.hidden = visible > 0;
      stat.textContent = visible ? '' : 'No changelog entries match this filter.';
    }
  }

  function renderMeta() {
    const root = dialog();
    const el = meta();
    if (!root || !el || !state.payload) return;
    const commitsLabel = root.dataset.labelCommits || 'commits';
    const techLabel = root.dataset.labelTechnical || 'technical';
    const mergeLabel = root.dataset.labelMerges || 'merge commits collapsed';
    const bits = [];
    if (state.payload.total_commits_seen) bits.push(`${state.payload.total_commits_seen} ${commitsLabel}`);
    if (state.payload.technical_commits) bits.push(`${state.payload.technical_commits} ${techLabel}`);
    if (state.payload.merge_commits_collapsed) bits.push(`${state.payload.merge_commits_collapsed} ${mergeLabel}`);
    bits.push(`source: ${state.payload.source || 'unknown'}`);
    el.textContent = bits.join(' · ');
    if (state.payload.warning) el.title = state.payload.warning;
  }

  async function load() {
    if (state.payload || state.loading) return;
    state.loading = true;
    const root = dialog();
    const stat = status();
    if (stat) {
      stat.hidden = false;
      stat.textContent = root?.dataset.labelLoading || 'Loading complete development history…';
    }
    try {
      const response = await fetch('/api/changelog/history', { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      const payload = await response.json();
      if (!response.ok || !payload || payload.ok === false) throw new Error('changelog unavailable');
      state.payload = payload;
      renderMeta();
      render();
    } catch (error) {
      if (stat) stat.textContent = root?.dataset.labelError || 'The changelog could not be loaded.';
    } finally {
      state.loading = false;
    }
  }

  function open() {
    const root = dialog();
    if (!root) return;
    if (typeof root.showModal === 'function') {
      if (!root.open) root.showModal();
    } else {
      root.setAttribute('open', '');
    }
    load();
  }

  function close() {
    const root = dialog();
    if (!root) return;
    if (typeof root.close === 'function' && root.open) root.close();
    else root.removeAttribute('open');
  }

  document.addEventListener('click', (event) => {
    const versionOpener = event.target.closest('.gc-bottom-util-version');
    if (versionOpener) {
      event.preventDefault();
      event.stopImmediatePropagation();
      open();
    }
  }, true);

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-gc-changelog-open]');
    if (opener) {
      event.preventDefault();
      open();
      return;
    }
    if (event.target.closest('[data-gc-changelog-close]')) {
      event.preventDefault();
      close();
      return;
    }
    const mode = event.target.closest('[data-gc-changelog-mode]');
    if (mode) {
      state.mode = mode.dataset.gcChangelogMode || 'player';
      document.querySelectorAll('[data-gc-changelog-mode]').forEach((btn) => {
        const active = btn === mode;
        btn.classList.toggle('is-active', active);
        btn.classList.toggle('gc-btn-primary', active);
        btn.classList.toggle('gc-btn-outline', !active);
      });
      render();
    }
  });

  document.addEventListener('input', (event) => {
    if (!event.target.matches('[data-gc-changelog-search]')) return;
    state.query = event.target.value || '';
    render();
  });

  document.addEventListener('cancel', (event) => {
    if (event.target.matches('[data-gc-changelog-dialog]')) close();
  });

  document.addEventListener('click', (event) => {
    const root = dialog();
    if (root && event.target === root) close();
  });

  window.GC = window.GC || {};
  window.GC.openPlayerChangelog = open;
})();
