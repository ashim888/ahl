// Homepage top-story slider (templates/home.html, [data-hero-slider]).
// Cover lines (one button per story), swipe and ←/→ keys; advances every 7 s, but never when the
// reader prefers reduced motion or is on a touch screen, and pauses while the pointer or keyboard
// focus is on it, or after the Pause button. Without this script the slides
// simply stack, so every top story is still reachable.
(function () {
  'use strict';
  var INTERVAL = 7000;
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  document.querySelectorAll('[data-hero-slider]').forEach(function (root) {
    var slides = Array.prototype.slice.call(root.querySelectorAll('[data-hero-slide]'));
    if (slides.length < 2) return;
    var dots = Array.prototype.slice.call(root.querySelectorAll('[data-hero-dot]'));
    var controls = root.querySelector('[data-hero-controls]');
    var status = root.querySelector('[data-hero-status]');
    var pauseButton = root.querySelector('[data-hero-pause]');
    var lines = root.querySelector('[data-hero-lines]');
    var current = 0;
    var timer = null;
    // Touch screens: no autoplay (the reader swipes or taps a cover line), so no pause button either.
    var touch = window.matchMedia && window.matchMedia('(hover: none)').matches;
    var userPaused = reduceMotion || touch;
    var hovering = false;
    var ready = false;
    root.style.setProperty('--hero-interval', INTERVAL + 'ms');

    controls.hidden = false;
    if (touch && pauseButton) pauseButton.hidden = true;
    else if (reduceMotion) setPauseLabel(true);

    function show(index, announce) {
      current = (index + slides.length) % slides.length;
      slides.forEach(function (slide, i) {
        var active = i === current;
        slide.hidden = !active;
        slide.classList.toggle('hero-slide--in', active && ready);
      });
      dots.forEach(function (dot, i) {
        var active = i === current;
        dot.setAttribute('aria-current', active ? 'true' : 'false');
      });
      // Phones: keep the current cover line in the sideways-scrolling rail's view
      // (scrollLeft, not scrollIntoView, so the page itself never jumps).
      if (lines && lines.scrollWidth > lines.clientWidth && dots[current]) {
        lines.scrollTo({left: dots[current].offsetLeft - lines.offsetLeft, behavior: reduceMotion ? 'auto' : 'smooth'});
      }
      if (announce && status) status.textContent = slides[current].getAttribute('aria-label') + ': ' +
        (slides[current].querySelector('h2') || {}).textContent.trim();
    }

    function setPauseLabel(paused) {
      if (!pauseButton) return;
      // The label names the action it will take; no aria-pressed, which would read "Play, pressed".
      pauseButton.textContent = paused ? pauseButton.dataset.labelPlay : pauseButton.dataset.labelPause;
    }

    // The current cover line's rule fills over the interval; restarted with the timer, cleared when it stops.
    function progress(running) {
      dots.forEach(function (dot) { dot.classList.remove('hero-line--run'); });
      if (!running || !dots[current]) return;
      void dots[current].offsetWidth; // restart the fill
      dots[current].classList.add('hero-line--run');
    }

    function stop() { if (timer) { clearInterval(timer); timer = null; } progress(false); }
    function start() {
      stop();
      if (userPaused || hovering) return;
      timer = setInterval(function () { show(current + 1, false); progress(true); }, INTERVAL);
      progress(true);
    }

    dots.forEach(function (dot, i) { dot.addEventListener('click', function () { show(i, true); start(); }); });
    if (pauseButton) pauseButton.addEventListener('click', function () {
      userPaused = !userPaused;
      setPauseLabel(userPaused);
      if (userPaused) stop(); else start();
    });

    root.addEventListener('mouseenter', function () { hovering = true; stop(); });
    root.addEventListener('mouseleave', function () { hovering = false; start(); });
    root.addEventListener('focusin', function () { hovering = true; stop(); });
    root.addEventListener('focusout', function (event) {
      if (!root.contains(event.relatedTarget)) { hovering = false; start(); }
    });
    root.addEventListener('keydown', function (event) {
      if (!event.target.closest('[data-hero-dot]')) return; // links inside the hero keep their keys
      if (event.key === 'ArrowLeft') { show(current - 1, true); event.preventDefault(); }
      if (event.key === 'ArrowRight') { show(current + 1, true); event.preventDefault(); }
    });

    // Swipe on touch screens.
    var startX = null;
    var track = root.querySelector('[data-hero-track]');
    track.addEventListener('touchstart', function (event) { startX = event.touches[0].clientX; }, {passive: true});
    track.addEventListener('touchend', function (event) {
      if (startX === null) return;
      var dx = event.changedTouches[0].clientX - startX;
      if (Math.abs(dx) > 40) { show(current + (dx < 0 ? 1 : -1), true); start(); }
      startX = null;
    });

    document.addEventListener('visibilitychange', function () { if (document.hidden) stop(); else start(); });

    show(0, false);
    ready = true;
    start();
  });
})();
