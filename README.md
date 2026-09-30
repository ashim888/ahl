# Ajna Health Lens

A health-news platform and editorial team workspace: public article/issue browsing, a subject
taxonomy (Sections), training courses, a subscription/paywall, reader comments, a newsletter,
house ads, and a full editorial dashboard for staff to run all of it.

Manuscript submission and peer review are handled externally by OJS (Open Journal Systems) —
this platform never builds that itself. The `submissions`/`peer_review` apps it started with were
removed from the codebase entirely in September 2026, once OJS took over. See `CLAUDE.md`'s SCOPE
NOTE.

## Stack

- **Backend**: Django 5.2, Python 3.12
- **Database**: MySQL 8.0
- **Frontend**: Tailwind CSS, compiled via the Tailwind CLI (not the `cdn.tailwindcss.com` Play
  CDN) — no other JS build step; templates are server-rendered Django templates with small,
  targeted vanilla-JS enhancements (no SPA framework)
- **Auth**: custom `User` model, email-based login, role-based access (unverified → verified
  author → editor → editor-in-chief → admin)
- **Async tasks**: Django-Q2, ORM-backed broker (no Redis)
- **Caching**: database-backed cache (no Redis/Memcached)

## Prerequisites

- Python 3.12
- MySQL 8.0, running locally with a database + user created for this project
- Node.js + npm (only needed to rebuild Tailwind CSS after a template change — the compiled
  output is committed to git, so it's *not* required just to run the server)
- On macOS, `mysqlclient` needs its native build deps first: `brew install mysql pkg-config`

## Setup

```bash
git clone <repo-url>
cd ahl

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — at minimum set a real SECRET_KEY and your local DB_* credentials,
# and DEBUG=True for local development (debug is off unless .env turns it on)
```

Create the database and a user matching your `.env` (charset must be `utf8mb4` — this project
uses it throughout, e.g. for full emoji/Devanagari support in the Nepali nav labels):

```sql
CREATE DATABASE ajna_health_lens CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ajna_user'@'localhost' IDENTIFIED BY 'your-db-password';
GRANT ALL PRIVILEGES ON ajna_health_lens.* TO 'ajna_user'@'localhost';
FLUSH PRIVILEGES;
```

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The site is now at `http://localhost:8000/` — `/` is the real homepage. (The old pre-launch
`/index/` URL permanently redirects there.) The editorial workspace is at
`http://localhost:8000/editorial/`.

### Background worker (Django-Q2)

Scheduled and bulk jobs run on a separate worker process, not inside web requests. Start it next
to `runserver` locally, and as its own service in production:

```bash
python manage.py qcluster
```

It publishes scheduled articles (every minute), runs newsletter sends, the weekly digests, and the
daily analytics clean-up (below). Without it, those jobs queue up but never run — including
scheduled articles, which then stay unpublished (`python manage.py publish_scheduled` does it by
hand).

### Email

Out of the box, emails print to the console. To send real mail, set these in `.env`:

```bash
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=mail.example.com
EMAIL_PORT=465              # 465 = implicit SSL (typical cPanel); 587 = STARTTLS
EMAIL_USE_SSL=True          # for port 465 (this forces EMAIL_USE_TLS off)
EMAIL_USE_TLS=False         # set True instead of EMAIL_USE_SSL for port 587
EMAIL_HOST_USER=noreply@example.com
EMAIL_HOST_PASSWORD=...
EMAIL_TIMEOUT=30
DEFAULT_FROM_EMAIL=noreply@example.com
SITE_BASE_URL=https://example.com   # used to build every link inside emails
```

Restart the app after changing `.env`. With `DEBUG=False`, `python manage.py check --deploy`
(run at the end of `deploy.sh`) reports an error if `SITE_BASE_URL` is still `localhost` or not
`https`, since every email link would be broken. `deploy.sh` runs this check first and **stops
before changing anything** if it finds an error: also when `DEBUG` is on (`ajna.E004`) or the
payment gateway is still the stub (`ajna.E003`). Warnings are printed and the deploy continues. Each migrate also re-syncs the comments package's site domain from it.

All emails share one branded layout (`templates/email/base.html`) with HTML and plain-text
versions: comment confirmation and follow-up, newsletter confirmation, welcome and issues,
account verification, pitch status updates, password reset, and staff alerts for new comments.

### Payments (Fonepay)

Checkout runs in **test mode** by default (`PAYMENT_GATEWAY=stub`: it always succeeds and no money
moves). To take real payments with Fonepay Checkout, set in `.env`:

```bash
PAYMENT_GATEWAY=fonepay
FONEPAY_API_URL=https://…/api/merchant/third-party/v2   # from Fonepay (dev/UAT/production differ)
FONEPAY_USERNAME=…
FONEPAY_PASSWORD=…
FONEPAY_PRIVATE_KEY=…      # Base64 PKCS#8 RSA key, without the BEGIN/END lines
FONEPAY_TERMINAL_ID=…      # your 16-digit merchant terminal ID
```

Readers then pay by scanning a Fonepay QR (desktop) or opening their bank app (mobile). Access is
granted only after the server confirms the payment with Fonepay's status API — never on the
browser's word — and only once. A background job (on the `qcluster` worker) settles payments whose
reader paid but closed the page. Payments are listed in Django admin under Billing → Payments.
Never commit Fonepay credentials; the `z_payment_instruction/` folder is git-ignored.

### Analytics retention

Article views, ad impressions/clicks and keyword impressions/clicks are recorded first-party.
Rows older than `ANALYTICS_RETENTION_DAYS` (default `400`) are deleted daily by the worker. To
prune by hand: `python manage.py prune_analytics_events [--days N]`.

### Frontend (Tailwind CSS)

The compiled stylesheet (`static/css/tailwind.css`) is committed to git, so a plain `pip
install` + `runserver` is enough to see fully-styled pages with no Node.js involved. Only
rebuild it after changing a Tailwind class in `templates/`:

```bash
npm install
npm run build:css    # one-off build
npm run watch:css    # rebuilds automatically while editing templates
```

### Translations (i18n)

The whole reader-facing interface (nav, footer, homepage, article pages, lists, search, issues,
comments, newsletter pages, reader messages) is available in English and Nepali via the
language switcher in the header. Article content (titles, abstracts, bodies, keywords) is not
translated — it stays in whatever language it was written in. Pages detect Devanagari text and
switch to Nepali-friendly typography (Noto Devanagari fonts, no letter-spacing or italics, taller
line height) automatically. Section names have separate English and Nepali fields.

After changing a `{% trans %}`-wrapped string or a translated model field, regenerate and edit
the catalogs:

```bash
python manage.py makemessages -l ne
# edit locale/ne/LC_MESSAGES/django.po
python manage.py compilemessages --locale=en --locale=ne --ignore=".venv/*"
```

## Running tests

```bash
python manage.py check                          # catches model/config errors
python manage.py makemigrations --check --dry-run  # fails if a model change wasn't migrated
python manage.py migrate
python manage.py test
```

Every app has its own `tests.py`; there's no single "critical path" suite to run selectively —
`python manage.py test` runs everything.

## Project layout

Each Django app owns one concern:

| App | Concern |
|---|---|
| `users` | Custom `User` model, auth, roles, verification |
| `articles` | Articles, author profiles and bylines (no login account needed), keywords, related reading, search, sitemaps/feeds, SEO structured data |
| `sections` | Two-level subject taxonomy (Journal, Policy & Economy, ...) driving the primary nav |
| `issues` | Curated article collections ("issues") |
| `editorial_board` | Public editorial board profiles |
| `training` | Paid training courses + enrollment |
| `billing` | Subscriptions, pay-per-article purchases, access control |
| `newsletter` | Free email newsletter, double opt-in, async bulk send |
| `ads` | House-sold ad zones, impressions/clicks |
| `pitches` | Public story-pitch intake → editorial review queue |
| `admin_custom` | The editorial dashboard (KPIs, BI analytics, keyword analytics, comment alerts, analytics retention) |

## Deployment

After pulling new code on the server: run `deploy.sh` (migrations, translations, static files,
checks), make sure the `qcluster` worker is running, and restart the app so `.env` changes take
effect. The compiled CSS (`static/css/tailwind.css`) is committed, so the server doesn't need
Node.js.

See `deploy.sh` (run after every `git pull` on the server) and `ARCHITECTURE.md` §9 for the full
environment-variable reference, production security settings, and hosting notes.

**Private files.** Article PDFs and CVs are stored in `PRIVATE_MEDIA_ROOT` (default
`private_media/`), not in `media/`, and are only served through `/protected-media/…`, which checks
on every request that the visitor may have the file (paid/subscribed for the article, or the CV's
owner or editorial staff). The web server must **not** serve that folder — only `/media/` and
`/static/`. The migration that introduced this moves existing PDFs and CVs across automatically.

**Checks.** `deploy.sh` runs `manage.py check --deploy` before anything else and stops on an
error, e.g. `ajna.E003` if the server would run with the stub payment gateway, which approves every
payment. Access rules for
every staff page are covered by `ajna_health_lens/test_access.py`, which walks every URL, so a new
`/manage/` page without a role check fails the test suite.

**Unused uploads.** `python manage.py quarantine_orphan_media` lists files in `media/` that
nothing references any more (replaced images, old uploads); `--move` moves them to
`media_orphans/` (not served, listed in its `manifest.tsv`), never deletes. Tests use temporary
media folders (`ajna_health_lens/test_runner.py`), so they no longer leave files behind.

Database and media backups (both `media/` and `private_media/`) are handled by `backup.sh` — not part of `deploy.sh`, meant to run on
its own schedule (a cron entry, e.g. nightly). See `ARCHITECTURE.md` §9.7a.

## Documentation map

- **`CLAUDE.md`** — project conventions, phase status, code standards
- **`ARCHITECTURE.md`** — schema, app-by-app design decisions, environment config, deployment
- **`ROADMAP.md`** — what's built, what's deferred, and why
- **`TUTORIAL.MD`** — task-oriented usage guide, by role
