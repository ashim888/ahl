// Article citations (templates/articles/article_detail.html): tapping a superscript
// number opens that source right under it, instead of jumping the reader to the list at
// the end. Escape, a tap elsewhere or the same number again closes it. Without this
// script the number is still a plain link to the reference list.
(function () {
  'use strict';
  var body = document.querySelector('[data-citations]');
  if (!body) return;
  var card = null;
  var openLink = null;

  function close(returnFocus) {
    if (!card) return;
    // Leave the way it came: shrink back toward the number, then go.
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

  // Under the number, or above it when the screen has no room below; kept inside the
  // viewport's side gutters. Coordinates are relative to the card's positioned parent,
  // because the card sits in the text right after the number (so screen readers reach it next).
  function place(link) {
    var rect = link.getBoundingClientRect();
    var gutter = 16;
    var gap = 8;
    var width = card.offsetWidth;
    var height = card.offsetHeight;
    var left = Math.min(Math.max(rect.left - 12, gutter), document.documentElement.clientWidth - width - gutter);
    var dock = document.querySelector('[data-mobile-dock]'); // the phone's fixed bottom bar covers the screen's foot
    var floor = window.innerHeight - (dock ? dock.offsetHeight : 0);
    var above = rect.bottom + gap + height > floor && rect.top - gap - height > 0;
    var top = above ? rect.top - gap - height : rect.bottom + gap;
    var parent = (card.offsetParent || document.body).getBoundingClientRect();
    card.style.top = (top - parent.top) + 'px';
    card.style.left = (left - parent.left) + 'px';
    // Grow out of (and shrink back into) the number that was tapped.
    card.style.transformOrigin = (rect.left + rect.width / 2 - left) + 'px ' + (above ? 'bottom' : 'top');
  }

  function open(link, source) {
    card = document.createElement('div');
    card.className = 'cite-card';
    card.id = 'cite-card';
    card.setAttribute('role', 'note');

    var label = document.createElement('p');
    label.className = 'cite-card__label';
    label.textContent = body.dataset.citeLabel + ' ' + link.textContent.trim();
    var text = document.createElement('div');
    text.className = 'cite-card__text';
    Array.prototype.forEach.call(source.childNodes, function (node) { text.appendChild(node.cloneNode(true)); });
    var all = document.createElement('a');
    all.className = 'cite-card__all';
    all.href = link.hash;
    all.textContent = body.dataset.citeAll;
    all.addEventListener('click', function () { close(false); });

    card.append(label, text, all);
    link.closest('sup').after(card);
    place(link);
    openLink = link;
    link.setAttribute('aria-expanded', 'true');
    link.setAttribute('aria-controls', 'cite-card');
  }

  body.addEventListener('click', function (event) {
    var link = event.target.closest('sup a[href^="#ref-"]');
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return;
    var source = document.getElementById(link.hash.slice(1));
    if (!source) return; // a number with no matching reference: let the link do what it does
    event.preventDefault();
    var same = link === openLink;
    close(false);
    if (!same) open(link, source);
  });

  document.addEventListener('click', function (event) {
    if (card && !card.contains(event.target) && !event.target.closest('sup a[href^="#ref-"]')) close(false);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && card) close(true);
  });
  window.addEventListener('resize', function () { close(false); });
})();
