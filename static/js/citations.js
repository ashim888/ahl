// Tap-to-read cards in an article (templates/articles/article_detail.html), one card for
// two kinds of tap, so they look and behave the same:
// - a citation number opens that source right under it, instead of jumping the reader to
//   the list at the end;
// - a health-glossary word (library/glossary_marking.py marks them; definitions arrive as
//   #glossary-data) opens its plain-language definition.
// Escape, a tap elsewhere or the same link again closes it. Without this script both are
// plain links: to the reference list, and to the term's glossary page.
(function () {
  'use strict';
  var body = document.querySelector('[data-citations]');
  if (!body) return;
  var CITATION = 'sup a[href^="#ref-"]';
  var GLOSSARY = 'a.glossary-term[data-glossary]';
  var glossary = {};
  var glossaryLabels = document.getElementById('glossary-labels');
  try { glossary = JSON.parse((document.getElementById('glossary-data') || {}).textContent || '{}'); } catch (e) { glossary = {}; }
  var card = null;
  var openLink = null;

  function close(returnFocus) {
    if (!card) return;
    // Leave the way it came: shrink back toward the link, then go.
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

  // Under the link, or above it when the screen has no room below; kept inside the
  // viewport's side gutters. Coordinates are relative to the card's positioned parent,
  // because the card sits in the text right after the link (so screen readers reach it next).
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
    // Grow out of (and shrink back into) the link that was tapped.
    card.style.transformOrigin = (rect.left + rect.width / 2 - left) + 'px ' + (above ? 'bottom' : 'top');
  }

  function element(tag, className, text) {
    var el = document.createElement(tag);
    el.className = className;
    if (text) el.textContent = text;
    return el;
  }

  // What goes in the card for this link, or null to let the link do what it does.
  function citationContent(link) {
    var source = document.getElementById(link.hash.slice(1));
    if (!source) return null; // a number with no matching reference
    var text = element('div', 'cite-card__text');
    Array.prototype.forEach.call(source.childNodes, function (node) { text.appendChild(node.cloneNode(true)); });
    var all = element('a', 'cite-card__all', body.dataset.citeAll);
    all.href = link.hash;
    all.addEventListener('click', function () { close(false); });
    return {className: '', parts: [element('p', 'cite-card__label', body.dataset.citeLabel + ' ' + link.textContent.trim()), text, all]};
  }

  function glossaryContent(link) {
    var term = glossary[link.dataset.glossary];
    if (!term || !glossaryLabels) return null; // no definition: open the glossary page
    var more = element('a', 'cite-card__all', glossaryLabels.dataset.more);
    more.href = term.url;
    return {className: 'glossary-card', parts: [
      element('p', 'cite-card__label', glossaryLabels.dataset.label),
      element('p', 'glossary-card__name', term.name),
      element('p', 'cite-card__text', term.definition),
      more,
    ]};
  }

  function open(link, content) {
    card = element('div', ('cite-card ' + content.className).trim());
    card.id = 'cite-card';
    card.setAttribute('role', 'note');
    content.parts.forEach(function (part) { card.appendChild(part); });
    (link.closest('sup') || link).after(card);
    place(link);
    openLink = link;
    link.setAttribute('aria-expanded', 'true');
    link.setAttribute('aria-controls', 'cite-card');
  }

  body.addEventListener('click', function (event) {
    var link = event.target.closest(CITATION + ', ' + GLOSSARY);
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return; // new tab: let the link work
    var content = link.matches(CITATION) ? citationContent(link) : glossaryContent(link);
    if (!content) return;
    event.preventDefault();
    var same = link === openLink;
    close(false);
    if (!same) open(link, content);
  });

  document.addEventListener('click', function (event) {
    if (card && !card.contains(event.target) && !event.target.closest(CITATION + ', ' + GLOSSARY)) close(false);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && card) close(true);
  });
  window.addEventListener('resize', function () { close(false); });
})();
