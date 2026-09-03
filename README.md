# Ajna Health Lens

A health-news platform and editorial team workspace: public article/issue browsing, a subject
taxonomy (Sections), training courses, a subscription/paywall, reader comments, a newsletter,
house ads, and a full editorial dashboard for staff to run all of it.

Manuscript submission and peer review are handled externally by OJS (Open Journal Systems) —
this platform's own `submissions`/`peer_review` apps are dormant, kept in the codebase but
unrouted. See `CLAUDE.md`'s SCOPE NOTE.

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
# edit .env — at minimum set a real SECRET_KEY and your local DB_* credentials
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

The site is now at `http://localhost:8000/`. Note: `/` is a pre-launch "Coming Soon" splash
page — the actual homepage is at `http://localhost:8000/index/` until launch (see `TUTORIAL.MD`).

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

Nav/UI chrome supports English and Nepali via a cookie-based language switcher (article content
stays single-language — see `ROADMAP.md`). After changing a `{% trans %}`-wrapped string or a
translated model field, regenerate and edit the catalogs:

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
| `articles` | Articles, keywords, search, sitemaps/feeds, SEO structured data |
| `sections` | Two-level subject taxonomy (Journal, Policy & Economy, ...) driving the primary nav |
| `issues` | Curated article collections ("issues") |
| `editorial_board` | Public editorial board profiles |
| `training` | Paid training courses + enrollment |
| `billing` | Subscriptions, pay-per-article purchases, access control |
| `newsletter` | Free email newsletter, double opt-in, async bulk send |
| `ads` | House-sold ad zones, impressions/clicks |
| `pitches` | Public story-pitch intake → editorial review queue |
| `admin_custom` | The editorial dashboard (KPIs, BI analytics) |
| `submissions`, `peer_review` | Dormant — see the SCOPE NOTE in `CLAUDE.md` |

## Deployment

See `deploy.sh` (run after every `git pull` on the server) and `ARCHITECTURE.md` §9 for the full
environment-variable reference, production security settings, and hosting notes.

## Documentation map

- **`CLAUDE.md`** — project conventions, phase status, code standards
- **`ARCHITECTURE.md`** — schema, app-by-app design decisions, environment config, deployment
- **`ROADMAP.md`** — what's built, what's deferred, and why
- **`TUTORIAL.MD`** — task-oriented usage guide, by role
