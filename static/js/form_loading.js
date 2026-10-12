// Loading state for every POST form (base.html): once a form is really
// being sent, its submit buttons are disabled (no double payments or
// duplicate pitches) and marked busy. A button with data-loading-text also
// shows a spinner and that text. Skipped when the submit was cancelled
// (confirm() said no, or JS handles the form) or the form has
// data-no-loading. Buttons come back when the page is restored from the
// back/forward cache, or after 12 s (a download, or a slow network).
(function () {
  'use strict';
  var SPINNER = '<svg class="inline-block w-3.5 h-3.5 mr-2 -mt-0.5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"></circle>' +
    '<path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" stroke-width="3" stroke-linecap="round"></path></svg>';
  var busy = [];

  function restore(button) {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.style.opacity = '';
    button.style.cursor = '';
    if (button.dataset.loadingOriginal !== undefined) {
      button.innerHTML = button.dataset.loadingOriginal;
      delete button.dataset.loadingOriginal;
    }
  }

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (event.defaultPrevented || !(form instanceof HTMLFormElement)) return;
    if ((form.getAttribute('method') || '').toLowerCase() !== 'post' || form.hasAttribute('data-no-loading')) return;
    if (form.target && form.target !== '_self') return;
    var buttons = Array.prototype.slice.call(form.querySelectorAll('button[type=submit], button:not([type]), input[type=submit]'));
    // Disable after the browser has captured the form data, so the clicked
    // button's name/value is still sent.
    setTimeout(function () {
      buttons.forEach(function (button) {
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.style.opacity = '0.6';
        button.style.cursor = 'progress';
        var text = button.dataset.loadingText;
        if (text && button.tagName === 'BUTTON' && (button === event.submitter || buttons.length === 1)) {
          button.dataset.loadingOriginal = button.innerHTML;
          button.innerHTML = SPINNER + text;
        }
        busy.push(button);
      });
      setTimeout(function () { buttons.forEach(restore); }, 12000);
    }, 0);
  });

  window.addEventListener('pageshow', function (event) {
    if (event.persisted) { busy.forEach(restore); busy = []; }
  });
})();
