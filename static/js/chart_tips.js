// Dashboard charts: shows an element's data-tip as a tooltip on hover, and
// on tap/click for touch screens (a native title never shows there). One
// tooltip for the page; Esc, scrolling or tapping elsewhere hides it.
(function () {
  var tip = document.createElement('div');
  tip.className = 'chart-tip';
  // Styled here, not in tailwind.css: that file's URL isn't versioned, so a
  // browser holding an older copy would leave the tooltip unstyled.
  tip.style.cssText = 'position:fixed;z-index:60;max-width:18rem;padding:.375rem .625rem;border-radius:.5rem;' +
    'background:#111827;color:#fff;font-size:.75rem;line-height:1.35;font-variant-numeric:tabular-nums;' +
    'box-shadow:0 6px 20px rgb(0 0 0/.18);pointer-events:none';
  tip.setAttribute('role', 'status');
  tip.hidden = true;
  document.body.appendChild(tip);
  var current = null;

  function show(el) {
    current = el;
    tip.textContent = el.getAttribute('data-tip');
    tip.hidden = false;
    var box = el.getBoundingClientRect();
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(8, box.left + box.width / 2 - w / 2), window.innerWidth - w - 8);
    var top = box.top - h - 8;
    if (top < 8) top = box.bottom + 8; // no room above: show it below
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }

  function hide() {
    current = null;
    tip.hidden = true;
  }

  document.addEventListener('pointerover', function (e) {
    if (e.pointerType !== 'mouse') return;
    var el = e.target.closest('[data-tip]');
    if (el) show(el); else if (current) hide();
  });
  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-tip]');
    if (el && el !== current) show(el); else hide();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); });
  window.addEventListener('scroll', hide, {passive: true});
})();
