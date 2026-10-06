// node --test tools/slug-checker-extension/test/  (npm run test:slug)
const test = require('node:test');
const assert = require('node:assert');
const S = require('../slug_quality.js');

const context = {title: 'Dengue cases rise in Kathmandu', keywords: ['Dengue']};

test('a short, hyphenated, on-topic slug is good', () => {
  const result = S.check('dengue-cases-rise-kathmandu', context);
  assert.strictEqual(result.grade, 'good');
  assert.strictEqual(result.issues.length, 0);
});

test('uppercase, underscores and punctuation are errors', () => {
  const codes = S.check('Dengue_Cases?', context).issues.map(i => i.code);
  for (const code of ['uppercase', 'separator', 'punctuation']) assert.ok(codes.includes(code), code);
});

test('length, filler words, repeats, years and generic slugs are flagged', () => {
  const codes = (slug) => S.check(slug, context).issues.map(i => i.code);
  assert.ok(codes('the-dengue-cases-are-rising-in-the-kathmandu-valley-this-monsoon-season-again-2026').includes('too_long'));
  assert.ok(codes('dengue-cases-in-kathmandu').includes('stopwords'));
  assert.ok(codes('dengue-dengue-cases').includes('repeated'));
  assert.ok(codes('dengue-cases-2026').includes('year'));
  assert.ok(codes('article-3f2a4').includes('generic'));
  assert.ok(codes('dengue--cases-').includes('hyphens'));
  assert.ok(codes('budget-speech').includes('no_focus_word'));
});

test('Nepali slugs are flagged and romanized suggestions offered', () => {
  const result = S.check('मानसिक-स्वास्थ्य', {title: 'मानसिक स्वास्थ्य'});
  assert.ok(result.issues.some(i => i.code === 'non_ascii'));
  assert.strictEqual(result.suggestion, 'manasik-swasthya');
});

test('romanize follows simple Nepali romanization', () => {
  const cases = {
    'निःसन्तान पनको समस्या र समाधान': 'nihsantan panako samasya ra samadhan',
    'मानसिक स्वास्थ्य': 'manasik swasthya', 'राष्ट्र': 'rashtra', 'क्षयरोग': 'kshayarog', 'ज्ञान': 'gyan',
    'डेंगु': 'dengu', 'नेपाल २०८३': 'nepal 2083',
  };
  for (const [input, expected] of Object.entries(cases)) assert.strictEqual(S.romanize(input), expected, input);
});

test('changing a published slug warns', () => {
  const result = S.check('new-slug', {published: true, original: 'old-slug'});
  assert.ok(result.issues.some(i => i.code === 'changed_after_publish'));
});

test('slugFromUrl takes the last path segment', () => {
  assert.strictEqual(S.slugFromUrl('https://example.com/articles/dengue-cases/'), 'dengue-cases');
  assert.strictEqual(S.slugFromUrl('dengue-cases'), 'dengue-cases');
});
