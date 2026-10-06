/* Type-ahead for search boxes marked data-search-suggest (base.html header).
   An accessible combobox: suggestions from /search/suggest/ as you type,
   ↑/↓ to move, Enter to open, Esc to close. Without JavaScript the form
   still submits to the full search page. */
(function () {
  document.querySelectorAll('form[data-search-suggest]').forEach(function (form, index) {
    var input = form.querySelector('input[name="q"]');
    if (!input) { return; }
    var listId = 'search-suggest-' + index;
    var list = document.createElement('ul');
    list.id = listId;
    list.setAttribute('role', 'listbox');
    list.className = 'hidden absolute left-0 right-0 top-full z-50 mt-1 bg-card border border-foreground shadow-xl text-left';
    form.style.position = 'relative';
    form.appendChild(list);
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', listId);
    input.setAttribute('autocomplete', 'off');

    var timer = null, active = -1, items = [], lastQuery = '';

    function close() {
      list.classList.add('hidden');
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      active = -1;
    }

    function highlight(index) {
      items.forEach(function (li, i) { li.setAttribute('aria-selected', i === index ? 'true' : 'false'); li.classList.toggle('bg-secondary', i === index); });
      active = index;
      if (index >= 0) { input.setAttribute('aria-activedescendant', items[index].id); } else { input.removeAttribute('aria-activedescendant'); }
    }

    function render(results) {
      list.innerHTML = '';
      items = results.map(function (result, i) {
        var li = document.createElement('li');
        li.id = listId + '-' + i;
        li.setAttribute('role', 'option');
        li.className = 'px-3 py-2 cursor-pointer border-b border-border last:border-0';
        var title = document.createElement('span');
        title.className = 'block text-sm font-medium leading-snug';
        title.textContent = result.title;
        li.appendChild(title);
        if (result.section) {
          var section = document.createElement('span');
          section.className = 'block font-mono-editorial text-[0.65rem] tracking-widest text-muted-foreground';
          section.textContent = result.section.toUpperCase();
          li.appendChild(section);
        }
        li.addEventListener('mousedown', function (event) { event.preventDefault(); window.location = result.url; });
        li.dataset.url = result.url;
        list.appendChild(li);
        return li;
      });
      if (items.length) {
        list.classList.remove('hidden');
        input.setAttribute('aria-expanded', 'true');
      } else {
        close();
      }
      active = -1;
    }

    input.addEventListener('input', function () {
      var query = input.value.trim();
      clearTimeout(timer);
      if (query.length < 2) { close(); return; }
      timer = setTimeout(function () {
        if (query === lastQuery) { return; }
        lastQuery = query;
        fetch('/search/suggest/?q=' + encodeURIComponent(query), {headers: {'Accept': 'application/json'}})
          .then(function (response) { return response.ok ? response.json() : {results: []}; })
          .then(function (data) { if (input.value.trim() === query) { render(data.results || []); } })
          .catch(close);
      }, 150);
    });

    input.addEventListener('keydown', function (event) {
      if (list.classList.contains('hidden')) { return; }
      if (event.key === 'ArrowDown') { event.preventDefault(); highlight(Math.min(active + 1, items.length - 1)); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); highlight(Math.max(active - 1, -1)); }
      else if (event.key === 'Escape') { close(); }
      else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); window.location = items[active].dataset.url; }
    });
    input.addEventListener('blur', function () { setTimeout(close, 150); });
  });
})();
