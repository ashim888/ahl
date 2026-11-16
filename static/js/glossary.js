// Health-glossary terms in an article (library/glossary_marking.py marks them; the
// definitions arrive as #glossary-data). Tapping a marked word opens its definition
// right under it, in the same card as citations (static/js/citations.js), so the
// reader never leaves the story. Escape, a tap elsewhere or the same word again closes
// it. Without this script a marked word is a plain link to its glossary page.
(function () {
  'use strict';
  var dataEl = document.getElementById('glossary-data');
  var labels = document.getElementById('glossary-labels');
  if (!dataEl || !labels) return;
  var terms;
  try { terms = JSON.parse(dataEl.textContent); } catch (e) { return; }
  var card = null;
  var openLink = null;

  function close(returnFocus) {
    if (!card) return;
    var leaving = card;
    leaving.removeAttribute('id');
    leaving.classList.add('cite-card--out');
    leaving.addEventListener('animationend', function () { leaving.remove(); }, {once: true});
    setTimeout(function () { leaving.remove(); }, 250); // no animation (reduced motion, hidden tab)
    card = null;
    openLink.setAttribute('aria-expanded', 'false');
    if (returnFocus) openLink.focus();
    openLink = null;
  }

  // Under the word, or above it when there's no room below; inside the side gutters.
  function place(link) {
    var rect = link.getBoundingClientRect();
    var gutter = 16;
    var gap = 8;
    var width = card.offsetWidth;
    var height = card.offsetHeight;
    var left = Math.min(Math.max(rect.left - 12, gutter), document.documentElement.clientWidth - width - gutter);
    var dock = document.querySelector('[data-mobile-dock]');
    var floor = window.innerHeight - (dock ? dock.offsetHeight : 0);
    var above = rect.bottom + gap + height > floor && rect.top - gap - height > 0;
    var top = above ? rect.top - gap - height : rect.bottom + gap;
    var parent = (card.offsetParent || document.body).getBoundingClientRect();
    card.style.top = (top - parent.top) + 'px';
    card.style.left = (left - parent.left) + 'px';
    card.style.transformOrigin = (rect.left + rect.width / 2 - left) + 'px ' + (above ? 'bottom' : 'top');
  }

  function open(link, term) {
    card = document.createElement('div');
    card.className = 'cite-card glossary-card';
    card.id = 'glossary-card';
    card.setAttribute('role', 'note');

    var label = document.createElement('p');
    label.className = 'cite-card__label';
    label.textContent = labels.dataset.label;
    var name = document.createElement('p');
    name.className = 'glossary-card__name';
    name.textContent = term.name;
    var text = document.createElement('p');
    text.className = 'cite-card__text';
    text.textContent = term.definition;
    var more = document.createElement('a');
    more.className = 'cite-card__all';
    more.href = term.url;
    more.textContent = labels.dataset.more;

    card.append(label, name, text, more);
    link.after(card);
    place(link);
    openLink = link;
    link.setAttribute('aria-expanded', 'true');
    link.setAttribute('aria-controls', 'glossary-card');
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest('a.glossary-term[data-glossary]');
    if (link) {
      if (event.metaKey || event.ctrlKey || event.shiftKey) return; // new tab: let the link work
      var term = terms[link.dataset.glossary];
      if (!term) return;
      event.preventDefault();
      var same = link === openLink;
      close(false);
      if (!same) open(link, term);
      return;
    }
    if (card && !card.contains(event.target)) close(false);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && card) close(true);
  });
  window.addEventListener('resize', function () { close(false); });
})();
