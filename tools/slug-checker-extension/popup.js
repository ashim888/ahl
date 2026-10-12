// Popup: checks the active tab's slug with slug_quality.js (the same file the
// Ajna Health Lens article editor uses). The page's headline (its <h1>, else
// <title>) and meta keywords give the checker context; the tab is read only
// when the popup is opened (activeTab), nothing is sent anywhere.
(function () {
  'use strict';
  var input = document.getElementById('input');
  var context = {};

  function render() {
    var slug = SlugQuality.slugFromUrl(input.value.trim());
    var result = SlugQuality.check(slug, context);
    var badge = document.getElementById('badge');
    badge.textContent = result.score;
    badge.className = 'badge ' + result.grade;
    document.getElementById('slug').textContent = slug ? decodeSafe(slug) : '(no slug)';
    var list = document.getElementById('issues');
    list.textContent = '';
    if (!result.issues.length) {
      var ok = document.createElement('li');
      ok.textContent = 'Looks good — short, readable and on topic.';
      list.appendChild(ok);
    }
    result.issues.forEach(function (issue) {
      var li = document.createElement('li');
      li.className = issue.level;
      var icon = document.createElement('b');
      icon.textContent = issue.level === 'error' ? '✕' : issue.level === 'warning' ? '!' : 'i';
      var text = document.createElement('span');
      text.textContent = issue.message;
      li.appendChild(icon);
      li.appendChild(text);
      list.appendChild(li);
    });
    var box = document.getElementById('suggestion-box');
    box.hidden = !result.suggestion;
    document.getElementById('suggestion').textContent = result.suggestion;
  }

  function decodeSafe(text) {
    try { return decodeURIComponent(text); } catch (e) { return text; }
  }

  document.getElementById('copy').addEventListener('click', function () {
    var button = this;
    navigator.clipboard.writeText(document.getElementById('suggestion').textContent).then(function () {
      button.textContent = 'Copied ✓';
      setTimeout(function () { button.textContent = 'Copy suggestion'; }, 1200);
    });
  });
  input.addEventListener('input', render);

  chrome.tabs.query({active: true, currentWindow: true}, function (tabs) {
    var tab = tabs && tabs[0];
    input.value = tab && tab.url ? tab.url : '';
    render();
    if (!tab || !/^https?:/.test(tab.url || '')) {
      document.getElementById('context').textContent = 'Open a web page to check its address, or paste a slug above.';
      return;
    }
    chrome.scripting.executeScript({
      target: {tabId: tab.id},
      func: function () {
        var h1 = document.querySelector('h1');
        var meta = document.querySelector('meta[name="keywords"]');
        return {
          title: (h1 && h1.innerText.trim()) || document.title,
          keywords: meta ? meta.content.split(',').map(function (k) { return k.trim(); }).filter(Boolean).slice(0, 5) : []
        };
      }
    }, function (results) {
      if (chrome.runtime.lastError || !results || !results[0]) return;
      context = results[0].result || {};
      document.getElementById('context').textContent = context.title ? 'Headline: ' + context.title : '';
      render();
    });
  });
})();
