#!/usr/bin/env bash
# Run this after every `git pull` on the production server (or staging) —
# every step here is idempotent (safe to run even when there's nothing new
# for it to do), so it's always safe to run the whole thing rather than
# guessing which steps this particular deploy actually needs.
#
# Usage (inside the project's virtualenv):
#   ./deploy.sh
#
# Does NOT touch Tailwind/npm by design — static/css/tailwind.css is a
# compiled build artifact committed to git (see package.json), rebuilt
# *locally* with `npm run build:css` before committing/pushing, not on the
# server. Shared hosting often has no usable Node.js, so production only
# ever needs to pick up the already-compiled file via collectstatic below.
# If npm happens to be available here anyway, this still offers to rebuild
# as a defensive safety net in case a change was pushed without rebuilding
# first — but it's optional, not a hard requirement.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> [1/5] Installing/updating Python dependencies"
pip install -r requirements.txt

echo "==> [2/5] Applying database migrations"
python manage.py migrate

echo "==> [3/5] Compiling i18n message catalogs (locale/*.po -> *.mo)"
# --locale + --ignore restrict this to just this project's own locale/ dir —
# compilemessages otherwise walks the whole working directory recursively,
# needlessly recompiling every installed package's own locale files too
# (django.contrib.*, django-comments-xtd, etc.) on every single deploy.
python manage.py compilemessages --locale=en --locale=ne --ignore=".venv/*"

echo "==> [4/5] Collecting static files (incl. the compiled Tailwind CSS)"
if command -v npm >/dev/null 2>&1; then
    echo "    npm found — rebuilding Tailwind CSS as a safety net (should normally be a no-op; the compiled file is committed)"
    npm install --silent
    npm run build:css --silent
else
    echo "    npm not found — using the compiled static/css/tailwind.css already committed to git, as expected on this host"
fi
python manage.py collectstatic --noinput

echo "==> [5/5] Production settings sanity check"
python manage.py check --deploy || echo "    (warnings above are informational — see ARCHITECTURE.md §9.1 for what each one means)"

# Phusion Passenger's standard restart convention (cPanel "Setup Python App"
# hosting, e.g. this project's ajnalab deployment) — touching this file
# tells Passenger to reload the app on the next request. Harmless/no-op
# under any other WSGI server that doesn't use this convention.
if [ -d "tmp" ]; then
    touch tmp/restart.txt
    echo "==> Touched tmp/restart.txt (Passenger will reload on the next request)"
fi

echo "==> Done."
