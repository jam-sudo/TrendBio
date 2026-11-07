const input = document.getElementById('header-search-query');
if (input) {
  const form = input.form;
  const panel = document.getElementById('header-search-panel');
  const list = document.getElementById('header-search-options');
  const message = document.getElementById('header-search-message');
  const status = document.getElementById('header-search-status');
  const all = document.getElementById('header-search-all');
  let modules, request = 0, timer, loading, active = -1;
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-expanded', 'false');
  input.autocomplete = 'off';

  function close() {
    ++request;
    clearTimeout(timer);
    clearTimeout(loading);
    panel.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
    status.textContent = '';
  }
  function fit() {
    const viewport = window.visualViewport;
    panel.style.setProperty('--search-height', `${Math.max(80, (viewport?.height ?? innerHeight) + (viewport?.offsetTop ?? 0) - input.getBoundingClientRect().bottom - 20)}px`);
  }
  function open(text) {
    fit();
    message.textContent = text;
    status.textContent = text;
    panel.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }
  function schedule() {
    close();
    list.replaceChildren();
    const query = input.value.trim();
    if (query.length < 2) return;
    const current = request;
    const isCurrent = () => current === request;
    all.href = `/search/?q=${encodeURIComponent(query)}`;
    all.hidden = true;
    timer = setTimeout(async () => {
      loading = setTimeout(() => { if (isCurrent()) open('Searching…'); }, 300);
      try {
        const [pagefind, match] = await modules;
        if (!isCurrent()) return;
        const search = await pagefind.search(query);
        if (!isCurrent()) return;
        const results = await match.firstMatches(query, search.results, isCurrent);
        if (!isCurrent()) return;
        clearTimeout(loading);
        for (const result of results) {
          const link = document.createElement('a');
          link.href = result.url;
          link.id = `header-result-${list.children.length}`;
          link.role = 'option';
          link.tabIndex = -1;
          link.setAttribute('aria-selected', 'false');
          link.textContent = result.meta.title;
          const category = document.createElement('small');
          category.textContent = result.filters.category.join(', ');
          link.append(category);
          list.append(link);
        }
        open(results.length ? '' : 'No topics found');
        status.textContent = results.length ? `${results.length} topics shown` : 'No topics found';
        all.hidden = false;
      } catch { if (isCurrent()) close(); }
    }, 150);
  }
  input.addEventListener('focus', () => {
    modules ??= Promise.all(['/pagefind/pagefind.js', '/search-match.js'].map(path => import(/* @vite-ignore */ path))).catch(() => null);
    if (innerWidth <= 640 && input.getBoundingClientRect().top > 96) form.scrollIntoView({ block: 'start' });
    schedule();
  });
  window.visualViewport?.addEventListener('resize', fit);
  input.addEventListener('input', schedule);
  input.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if (event.key === 'Escape' || event.key === 'Tab') {
      if (event.key === 'Escape') event.preventDefault();
      close();
      return;
    }
    const options = [...list.children];
    if (panel.hidden || !options.length) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = (active + (event.key === 'ArrowDown' ? 1 : active < 0 ? 0 : -1) + options.length) % options.length;
      options.forEach((option, index) => option.setAttribute('aria-selected', String(index === active)));
      input.setAttribute('aria-activedescendant', options[active].id);
      options[active].scrollIntoView({ block: 'nearest' });
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      options[active].click();
    }
  });
  document.addEventListener('pointerdown', event => { if (!form.contains(event.target)) close(); });
  form.addEventListener('focusout', event => { if (!form.contains(event.relatedTarget)) close(); });
}
