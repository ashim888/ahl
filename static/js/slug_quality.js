/*
 * Slug quality checker — one file, three users:
 *   - the article editor (templates/articles/manage/article_form.html): live
 *     checks under the "URL slug" field and a suggested slug;
 *   - the Chrome extension (tools/slug-checker-extension/, a copy made by
 *     `npm run build:extension`);
 *   - node tests (tools/slug-checker-extension/test/).
 *
 * check(slug, context) → {score 0–100, grade, issues[], suggestion}
 *   context (optional): {title, keywords: [..], published: bool, original: 'old-slug'}
 * suggest(title, keywords) → a short, lowercase, hyphenated ASCII slug.
 * romanize(text) → Devanagari to Latin letters (स्वास्थ्य → swasthya),
 *   mirrored by articles/transliterate.py for slugs made on the server.
 *
 * The rules follow common SEO guidance (Google Search Central's URL structure
 * guide, Moz/Ahrefs/Yoast slug advice): short, lowercase, words joined by
 * hyphens, readable letters only, no filler words, the topic in it, no dates
 * that age the page, and don't change it once published.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SlugQuality = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STOPWORDS = ('a an the and or but nor of in on at to for from by with as is are was were be been being it its ' +
    'this that these those into about over after before than then so if not no yes can will just how why what ' +
    'when where who which do does did has have had your our their his her you we they i me my ' +
    'ra ko ka ki ma le lai chha chhan ho pani tatha wa evam').split(' ');
  var GENERIC = ['article', 'untitled', 'new-article', 'post', 'news', 'page', 'draft', 'test', 'copy', 'story'];
  var MAX_GOOD = 60, MAX_OK = 75, WORDS_MAX = 8;

  // ---- Devanagari → Latin (simple, readable Nepali romanization) --------
  var CONSONANTS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng', 'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'n',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n', 'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm', 'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'w', 'श': 'sh',
    'ष': 'sh', 'स': 's', 'ह': 'h', 'क्ष': 'ksh', 'ज्ञ': 'gy', 'ड़': 'r', 'ढ़': 'rh', 'फ़': 'f', 'ज़': 'z'
  };
  var VOWELS = {
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'i', 'उ': 'u', 'ऊ': 'u', 'ऋ': 'ri', 'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au',
    'ऍ': 'e', 'ऑ': 'o'
  };
  var SIGNS = {
    'ा': 'a', 'ि': 'i', 'ी': 'i', 'ु': 'u', 'ू': 'u', 'ृ': 'ri', 'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au',
    'ॅ': 'e', 'ॉ': 'o'
  };
  var MARKS = {'ं': 'n', 'ँ': 'n', 'ः': 'h', '़': '', 'ऽ': ''};
  var DIGITS = '०१२३४५६७८९';
  var VIRAMA = '्';

  function romanize(text) {
    var out = '';
    var chars = Array.from(text || '');
    var wordStart = 0;          // where the current word starts in `out`
    var afterVirama = false;    // the previous consonant joined this one (स्थ्य)
    for (var i = 0; i < chars.length; i++) {
      var ch = chars[i];
      var triple = ch + (chars[i + 1] || '') + (chars[i + 2] || '');
      if (chars[i + 1] === VIRAMA && CONSONANTS[triple]) { ch = triple; i += 2; }  // क्ष, ज्ञ
      else if (chars[i + 1] === '़' && CONSONANTS[ch + '़']) { ch = ch + '़'; i += 1; }  // nukta forms
      if (CONSONANTS[ch]) {
        out += CONSONANTS[ch];
        var next = chars[i + 1];
        if (next === VIRAMA) { i += 1; afterVirama = true; continue; }
        if (next && SIGNS[next] !== undefined) { out += SIGNS[next]; i += 1; }
        else if (!isWordEnd(chars, i + 1)) { out += 'a'; }
        // The inherent "a" is silent at a word's end (समाधान → samadhan) —
        // unless the word is a single letter (र → ra) or ends in a
        // conjunct (स्वास्थ्य → swasthya).
        else if (afterVirama || !/[aeiou]/.test(out.slice(wordStart, -CONSONANTS[ch].length))) { out += 'a'; }
        afterVirama = false;
        continue;
      }
      afterVirama = false;
      if (VOWELS[ch]) {
        out += VOWELS[ch];
      } else if (MARKS[ch] !== undefined) {
        out += MARKS[ch];
      } else if (DIGITS.indexOf(ch) >= 0) {
        out += String(DIGITS.indexOf(ch));
      } else if (ch === '।' || ch === '॥') {
        out += ' ';
      } else {
        out += ch;
      }
      if (!/[\u0900-\u097F]/.test(ch)) wordStart = out.length;
    }
    return out.replace(/aa(?=[^aeiou]|$)/g, 'a');
  }

  function isWordEnd(chars, j) {
    var c = chars[j];
    if (c === undefined) return true;
    if (MARKS[c] !== undefined && MARKS[c] !== '') return false;
    return !/[ऀ-ॿ]/.test(c);
  }

  // ---- Helpers -----------------------------------------------------------
  function asciiFold(text) {
    return text.normalize('NFKD').replace(/[̀-ͯ]/g, '');
  }

  function words(text) {
    return asciiFold(romanize(String(text || '')).toLowerCase())
      .replace(/['’]/g, '')
      .split(/[^a-z0-9]+/)
      .filter(Boolean);
  }

  function suggest(title, keywords) {
    var meaningful = words(title).filter(function (w) { return STOPWORDS.indexOf(w) < 0; });
    var picked = [];
    meaningful.forEach(function (w) {
      if (picked.indexOf(w) < 0 && picked.length < 6 && (picked.join('-') + '-' + w).length <= MAX_GOOD) picked.push(w);
    });
    var focus = (keywords || []).map(function (k) { return words(k).join('-'); }).filter(Boolean)[0];
    if (focus && picked.join('-').indexOf(focus) < 0 && (focus + '-' + picked.join('-')).length <= MAX_GOOD) {
      picked = focus.split('-').concat(picked.filter(function (w) { return focus.split('-').indexOf(w) < 0; })).slice(0, 6);
    }
    return picked.join('-');
  }

  // ---- The checks --------------------------------------------------------
  function check(slug, context) {
    context = context || {};
    slug = String(slug || '').trim();
    var issues = [];
    function add(level, code, message) { issues.push({level: level, code: code, message: message}); }

    var decoded = slug;
    try { decoded = decodeURIComponent(slug); } catch (e) { /* keep as typed */ }

    if (!decoded) {
      add('error', 'empty', 'No slug yet — one will be made from the headline. Write a short one yourself for a better address.');
    } else {
      if (/[ऀ-ॿ]/.test(decoded)) {
        add('warning', 'non_ascii', 'Nepali letters turn into long codes (%E0%A4…) when the link is copied or shared — use English or romanized words.');
      } else if (/[^\x00-\x7F]/.test(decoded)) {
        add('warning', 'non_ascii', 'Accented or special letters get encoded in shared links — use plain a–z letters.');
      }
      if (decoded !== decoded.toLowerCase()) add('error', 'uppercase', 'Use lowercase only — some servers treat “Dengue” and “dengue” as different pages.');
      if (/[_\s]/.test(decoded)) add('error', 'separator', 'Separate words with hyphens (-), not spaces or underscores — search engines read hyphens as spaces.');
      if (/[^a-zA-Z0-9\-_\s\u0080-￿]/.test(decoded)) add('error', 'punctuation', 'Remove punctuation and symbols (?, &, %, ., /…).');
      if (/--/.test(decoded) || /^-|-$/.test(decoded)) add('error', 'hyphens', 'No double hyphens, and no hyphen at the start or end.');

      var parts = decoded.toLowerCase().split(/[-_\s]+/).filter(Boolean);
      var codeSuffix = parts.length > 1 && /^[a-z0-9]{5}$/.test(parts[parts.length - 1]) && /\d/.test(parts[parts.length - 1]) && /[a-z]/.test(parts[parts.length - 1]);
      var meaningful = codeSuffix ? parts.slice(0, -1) : parts;

      if (GENERIC.indexOf(meaningful.join('-')) >= 0 || !meaningful.length) {
        add('error', 'generic', 'Says nothing about the story — readers and Google can’t tell what the page is from “' + decoded + '”.');
      } else if (/^\d+$/.test(meaningful.join(''))) {
        add('error', 'numbers_only', 'Only numbers — add the words the story is about.');
      }
      if (decoded.length > MAX_OK) add('error', 'too_long', decoded.length + ' characters — keep it under ' + MAX_GOOD + '. Long addresses are cut off in search results.');
      else if (decoded.length > MAX_GOOD) add('warning', 'long', decoded.length + ' characters — a little long; ' + MAX_GOOD + ' or fewer is best.');
      if (meaningful.length > WORDS_MAX) add('warning', 'many_words', meaningful.length + ' words — 3 to 6 is ideal.');
      else if (meaningful.length === 1 && decoded.length < 12) add('warning', 'one_word', 'One word is vague — add one or two more (e.g. “dengue-cases-kathmandu”).');

      var stop = meaningful.filter(function (w) { return STOPWORDS.indexOf(w) >= 0; });
      if (stop.length) add('warning', 'stopwords', 'Filler words add length, not meaning: ' + unique(stop).join(', ') + '.');
      var repeats = meaningful.filter(function (w, i) { return meaningful.indexOf(w) !== i; });
      if (repeats.length) add('warning', 'repeated', 'Repeated word: ' + unique(repeats).join(', ') + ' — repeating keywords looks spammy.');
      if (meaningful.some(function (w) { return /^(19|20)\d\d$/.test(w) || /^20[78]\d$/.test(w); })) {
        add('tip', 'year', 'A year makes the address look out of date later — leave it out unless the date is the story.');
      }
      if (codeSuffix) add('tip', 'code_suffix', 'The “-' + parts[parts.length - 1] + '” code keeps the address unique but means nothing to readers; drop it if the rest is unique.');

      var focus = [];
      (context.keywords || []).forEach(function (k) { focus.push(words(k)); });
      if (context.title) {
        var titleWords = words(context.title).filter(function (w) { return STOPWORDS.indexOf(w) < 0 && w.length > 2; });
        if (titleWords.length) focus.push(titleWords);
      }
      if (focus.length) {
        var hit = focus.some(function (group) { return group.some(function (w) { return meaningful.indexOf(w) >= 0; }); });
        if (!hit) add('warning', 'no_focus_word', 'None of the headline’s or topics’ main words are in it — include the main subject people search for.');
      }
    }
    if (context.published && context.original && context.original !== slug) {
      add('warning', 'changed_after_publish', 'This story is already published: changing the slug changes its address, so links already shared and search results will break.');
    }

    var score = 100;
    issues.forEach(function (issue) { score -= issue.level === 'error' ? 30 : issue.level === 'warning' ? 12 : 4; });
    score = Math.max(0, score);
    var suggestion = context.title ? suggest(context.title, context.keywords) : '';
    if (suggestion === slug) suggestion = '';
    return {
      score: score,
      grade: score >= 85 && !issues.some(function (i) { return i.level === 'error'; }) ? 'good' : score >= 60 ? 'ok' : 'poor',
      issues: issues,
      suggestion: suggestion
    };
  }

  function unique(list) {
    return list.filter(function (x, i) { return list.indexOf(x) === i; });
  }

  /** The slug part of a URL: its last path segment. */
  function slugFromUrl(url) {
    try {
      var path = new URL(url).pathname.replace(/\/+$/, '');
      return path.split('/').pop() || '';
    } catch (e) {
      return String(url || '').replace(/\/+$/, '').split('/').pop();
    }
  }

  return {check: check, suggest: suggest, romanize: romanize, slugFromUrl: slugFromUrl, MAX_GOOD: MAX_GOOD};
});
