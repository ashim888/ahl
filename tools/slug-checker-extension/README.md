# Slug Quality Checker (Chrome extension)

Checks the slug — the last part of a page's address — against SEO best practice
and suggests a better one. Works on any website; built for the Ajna Health Lens
newsroom, whose article editor runs the very same checks live
(`static/js/slug_quality.js`).

**What it checks:** lowercase only; words joined by hyphens (no spaces,
underscores, punctuation or double hyphens); 60 characters or fewer, 3–6 words;
no filler words (the, of, and… and Nepali ra, ko, ma…); no repeated words; no
year that ages the page; no generic slugs ("article-3f2a4"); readable a–z letters
(Nepali letters become `%E0%A4…` codes when shared — it suggests a romanized
slug instead: मानसिक स्वास्थ्य → `manasik-swasthya`); and that the headline's or
topics' main words are in it. Score out of 100: good (85+, no errors), ok (60+),
poor.

**Privacy:** it reads the open tab's address, headline (`<h1>`) and meta
keywords only when you click the icon, and sends nothing anywhere.

## Install (for the team)

1. `npm run build:extension` (copies the latest `slug_quality.js` in here).
2. Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** →
   choose this folder.
3. Pin it, open any article, click the icon. You can also paste any slug or URL
   into the box.

## Publish to the Chrome Web Store (optional)

Zip this folder (`zip -r slug-checker.zip . -x 'test/*'`), create a developer
account at https://chrome.google.com/webstore/devconsole (one-time US$5 fee),
upload the zip, and use the description and privacy note above. Permissions
used: `activeTab` and `scripting` — only to read the open page's headline when
the popup is opened.

## Tests

`npm run test:slug` (Node 18+). The Django suite also checks this copy matches
`static/js/slug_quality.js` and that the JS and Python romanizers agree.
