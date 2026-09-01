"""
Django settings for ajna_health_lens project.

See CLAUDE.md and ARCHITECTURE.md for the full spec this file implements.
"""

import datetime
import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only-change-me')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DEBUG', True)

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
if DEBUG:
    # Django's test Client sends Host: testserver by default — allow it in
    # dev/test only, never in production.
    ALLOWED_HOSTS.append('testserver')

# Used to build absolute links (confirm/unsubscribe) inside emails sent from
# a background task (newsletter/tasks.py), where there's no request to pull
# a domain from. No trailing slash.
SITE_BASE_URL = os.environ.get('SITE_BASE_URL', 'http://localhost:8000')


# Production security hardening — every setting here defaults to a no-op in
# dev (DEBUG=True) so nothing changes locally; each only takes its real
# value once DEBUG=False in an actual deployment. These are exactly the
# gaps `manage.py check --deploy` flags (W004/W008/W012/W016) when absent.
# Individually env-overridable in case a specific deployment terminates TLS
# somewhere in front of Django (a load balancer, etc.) and needs different values.
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', not DEBUG)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = env_bool('SECURE_CONTENT_TYPE_NOSNIFF', True)
# HSTS is the one setting here that's actively harmful to turn on
# accidentally in dev/staging (browsers cache it stubbornly), hence 0 unless
# DEBUG=False — a deployment should raise this once HTTPS is confirmed working.
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0' if DEBUG else str(60 * 60 * 24 * 365)))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', not DEBUG)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', not DEBUG)
X_FRAME_OPTIONS = os.environ.get('X_FRAME_OPTIONS', 'DENY')


# Application definition

INSTALLED_APPS = [
    # Must come before django.contrib.admin — it patches the admin to add
    # per-language fields for any model registered in a translation.py.
    'modeltranslation',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'django.contrib.sites',   # required by django_comments / django_comments_xtd
    'django_q',
    'axes',
    'django_ckeditor_5',
    'rest_framework',        # required by django_comments_xtd's comment API
    'django_comments',
    'django_comments_xtd',

    # Ajna Health Lens apps
    'users',
    'articles',
    'submissions',   # dormant — see ARCHITECTURE.md §4.4 / ROADMAP.md "Scope Pivot"
    'peer_review',   # dormant — see ARCHITECTURE.md §4.4 / ROADMAP.md "Scope Pivot"
    'issues',
    'sections',
    'admin_custom',
    'training',
    'editorial_board',
    'billing',
    'newsletter',
    'ads',
    'pitches',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Must sit after SessionMiddleware, before CommonMiddleware (Django's
    # documented ordering) — reads the django_language cookie/session key set
    # by the set_language view (see urls.py) and activates it for the
    # request. Cookie/session-based, not URL-prefixed, since public and
    # /manage/ routes are interleaved in one urls.py per app.
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # django-axes' docs require this to be the last middleware in the list —
    # it reads a lockout flag AxesStandaloneBackend leaves on the request
    # (see AUTHENTICATION_BACKENDS/AXES_* below) and, only then, rewrites the
    # response into a 429. Debug Toolbar inserts itself at index 1 below,
    # which doesn't disturb this middleware staying last.
    'axes.middleware.AxesMiddleware',
]

# Django Debug Toolbar — dev-only, entirely gated behind DEBUG so it's never
# installed/active in production regardless of what's in INSTALLED_APPS
# above. Needs INTERNAL_IPS to actually render (see below).
if DEBUG:
    INSTALLED_APPS.append('debug_toolbar')
    # As early as possible, but after SecurityMiddleware per the toolbar's docs.
    MIDDLEWARE.insert(1, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = [h.strip() for h in os.environ.get('INTERNAL_IPS', '127.0.0.1,::1').split(',') if h.strip()]

ROOT_URLCONF = 'ajna_health_lens.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
                'ajna_health_lens.context_processors.journal_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'ajna_health_lens.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'ajna_health_lens'),
        'USER': os.environ.get('DB_USER', 'ajna_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    }
}


# Custom user model
AUTH_USER_MODEL = 'users.User'


# Account-level login lockout (django-axes) — complements, not replaces, the
# per-IP django_ratelimit throttle already on EmailLoginView (15/m; see
# users/views.py). Rate limiting alone doesn't stop a slow/distributed
# attacker rotating IPs against one account — axes tracks failures by
# username (email) instead, independent of source IP. AxesStandaloneBackend
# must be first so a locked-out account is rejected before ModelBackend ever
# checks the password.
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]
AXES_FAILURE_LIMIT = 5
AXES_LOCKOUT_PARAMETERS = ['username']
# django.contrib.auth.forms.AuthenticationForm always names its field
# "username" — even though User.USERNAME_FIELD is "email" — so axes' default
# of reading USERNAME_FIELD ("email") from POST data looks for a key that's
# never actually sent and silently tracks nothing. Point it at the real field.
AXES_USERNAME_FORM_FIELD = 'username'
# Auto-expires the lockout rather than requiring an admin to manually clear
# it in Django admin (axes.AccessAttempt) — 30 minutes is enough friction to
# stop a credential-stuffing run without locking a real reader out for long.
AXES_COOLOFF_TIME = datetime.timedelta(minutes=30)
AXES_RESET_ON_SUCCESS = True
# axes.W006 warns that username-only lockout doesn't stop an attacker who
# rotates IPs/cookies — true, but that's deliberately EmailLoginView's job
# (per-IP ratelimit) rather than axes'; the two are complementary, not
# redundant, by design (see the AUTHENTICATION_BACKENDS comment above).
SILENCED_SYSTEM_CHECKS = ['axes.W006']


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

# Nav/UI-chrome translation only for now (see ROADMAP.md) — article content
# stays single-language. Needed here (not just at the LocaleMiddleware/
# set_language wiring, further down this file) because django-modeltranslation
# reads LANGUAGES at app-loading time to decide which per-language columns
# (e.g. Section.name_en/name_ne) to generate.
LANGUAGES = [
    ('en', 'English'),
    ('ne', 'नेपाली'),
]

TIME_ZONE = 'Asia/Kathmandu'

# Where makemessages/compilemessages read and write .po/.mo catalogs (see
# locale/en/LC_MESSAGES/django.po, locale/ne/LC_MESSAGES/django.po) —
# project-level, not per-app, since the tagged strings are only in shared
# templates (base.html and its includes), not app-specific templates.
LOCALE_PATHS = [BASE_DIR / 'locale']

USE_I18N = True

USE_TZ = True

# django-modeltranslation — powers per-language fields on registered models
# (see e.g. sections/translation.py). Kept next to LANGUAGES/USE_I18N since
# it's part of the same i18n story, even though the rest of the request-time
# language machinery (LocaleMiddleware, set_language) lives further down.
MODELTRANSLATION_DEFAULT_LANGUAGE = 'en'
MODELTRANSLATION_LANGUAGES = ('en', 'ne')


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
# Env-overridable, same `or` reasoning as MEDIA_ROOT below — a deployment
# can point collectstatic wherever it actually needs to serve static files
# from (ARCHITECTURE.md §9 documents this as configurable; it needs to
# actually be configurable for that to be true).
STATIC_ROOT = Path(os.environ.get('STATIC_ROOT') or BASE_DIR / 'staticfiles')

# Media files (user uploads: manuscripts, CVs, article PDFs, covers).
# In production, Django itself does NOT serve these (see the DEBUG check in
# ajna_health_lens/urls.py) — the web server (nginx/Apache) serves /media/
# directly from MEDIA_ROOT. Both are env-overridable so a deployment can
# point them at wherever media actually lives on that host, and MEDIA_URL
# can become a full CDN domain later (e.g. https://cdn.example.com/media/)
# without any code change — see ARCHITECTURE.md §9 for the nginx config.
# `or` (not a .get default) so an empty value in .env — e.g. an unedited
# MEDIA_ROOT= left over from .env.example — falls back too, instead of
# resolving to '' (MEDIA_ROOT='' would silently mean "the cwd").
MEDIA_URL = os.environ.get('MEDIA_URL') or '/media/'
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT') or BASE_DIR / 'media')


# CKEditor 5 (django-ckeditor-5) — WYSIWYG editing for the "trusted,
# editor-authored HTML" fields that used to be plain <textarea>s an editor
# had to hand-write raw HTML into (Article.html_content, NewsletterIssue.body_html;
# see ARCHITECTURE.md §4.2/§4.10). `articles` config adds a "sourceEditing"
# button so a technical editor can still drop into raw HTML when they need
# to (e.g. an embedded D3.js chart, ARCHITECTURE.md's chart-embedding note)
# — WYSIWYG is the default view, not the only option. Citations are typed
# as plain [1], [2] placeholders (see articles/citations.py) rather than
# needing hand-written <sup><a href="#ref-1"> markup at all.
CKEDITOR_5_CONFIGS = {
    'default': {
        'toolbar': [
            'heading', '|', 'bold', 'italic', 'link', 'bulletedList', 'numberedList',
            'blockQuote', '|', 'undo', 'redo',
        ],
    },
    'articles': {
        'toolbar': [
            'heading', '|', 'bold', 'italic', 'underline', 'link', '|',
            'bulletedList', 'numberedList', 'blockQuote', 'insertTable', '|',
            'code', 'codeBlock', '|',
            'undo', 'redo', '|', 'sourceEditing',
        ],
        'table': {
            'contentToolbar': ['tableColumn', 'tableRow', 'mergeTableCells'],
        },
        # Language options for the "codeBlock" dropdown (a methodology paper
        # describing an analysis script, most plausibly) — each renders as
        # <pre><code class="language-{language}">, which is what the
        # .prose-article pre/code CSS in templates/base.html styles. Not
        # wired to a real syntax highlighter (no JS highlighting library is
        # loaded) — the class is there for whichever highlighter gets added
        # later, or just as a readable label for now.
        'codeBlock': {
            'languages': [
                {'language': 'plaintext', 'label': 'Plain text'},
                {'language': 'python', 'label': 'Python'},
                {'language': 'r', 'label': 'R'},
                {'language': 'sql', 'label': 'SQL'},
                {'language': 'javascript', 'label': 'JavaScript'},
                {'language': 'bash', 'label': 'Shell'},
                {'language': 'json', 'label': 'JSON'},
            ],
        },
    },
}
# django-ckeditor-5's built-in upload-permission check only understands two
# modes: "staff" (request.user.is_staff) or "authenticated". Neither maps
# onto this project's role-based RBAC — Editor/EiC/Admin accounts don't get
# is_staff=True here (see users/forms.py StaffCreateForm, ARCHITECTURE.md
# §6.2), so "staff" would lock real editors out, and "authenticated" would
# let any logged-in reader hit the upload endpoint directly. Real
# enforcement (EDITORIAL_ROLES) happens in the wrapper view at
# ajna_health_lens/ckeditor_views.py, which is registered under this same
# view name instead of the package's own urls.py — this setting is left at
# "authenticated" so the package's own inner check, which still runs after
# the wrapper's, is just a harmless pass-through rather than a second,
# conflicting gate.
CKEDITOR_5_FILE_UPLOAD_PERMISSION = 'authenticated'


# Reader comments (django-comments-xtd) — threaded comments on articles.
# django.contrib.sites (SITE_ID) is a hard dependency of django_comments;
# its Site row's `domain` is kept in sync with SITE_BASE_URL above by a data
# migration (articles/migrations/0019_sync_site_domain.py) so confirmation/
# follow-up emails link back to the real site instead of the "example.com"
# the sites migration creates by default.
SITE_ID = 1
COMMENTS_APP = 'django_comments_xtd'

# Nesting depth for replies (0 = flat, no replies at all). 3 matches what
# most news/blog comment sections use in practice — deep enough for a real
# back-and-forth, shallow enough that a reply thread doesn't need its own UI.
COMMENTS_XTD_MAX_THREAD_LEVEL = 3

# Anonymous commenters must confirm via a one-click emailed link before
# their comment goes live (django-comments-xtd's own anti-spam mechanism,
# no CAPTCHA needed) — logged-in readers post immediately. See
# COMMENTS_XTD_APP_MODEL_OPTIONS default ("who_can_post": "all") for who's
# allowed to post at all; this only governs anonymous ones specifically.
COMMENTS_XTD_CONFIRM_EMAIL = True

# Every other synchronous-email flow in this project (users/signals.py,
# newsletter/emails.py, pitches/signals.py) sends inline rather than
# spinning up its own async mechanism — comment confirmation/follow-up
# emails are one-at-a-time, not a bulk send, so they don't need Django-Q2
# either. False here keeps that the one pattern, instead of adding raw
# background threading (the package's default) as a second one.
COMMENTS_XTD_THREADED_EMAILS = False

# Our custom User model (users.User) has no `username` field — email is the
# USERNAME_FIELD (see CLAUDE.md). The package's default COMMENTS_XTD_API_USER_REPR
# assumes `u.username`, so it's overridden here; only used by the comment
# API's like/dislike user lists.
COMMENTS_XTD_API_USER_REPR = lambda u: u.get_full_name() or u.email  # noqa: E731

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Auth redirects
LOGIN_URL = 'users:login'
# '/' is the pre-launch "coming soon" placeholder (see articles/urls.py) — a
# freshly logged-in user should land on the real homepage, not the splash.
# Logging out, by contrast, correctly drops an anonymous visitor back there.
LOGIN_REDIRECT_URL = 'articles:home'
LOGOUT_REDIRECT_URL = '/'


# Email
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@ajnahealthlens.example')


# Cache — DB-backed (django_cache_table, via `manage.py createcachetable`),
# not Redis/Memcached, matching the project's no-extra-infra pattern (see
# Q_CLUSTER above — same reasoning). LocMemCache (Django's default) is
# per-process and useless once more than one worker process runs, so
# something real needs to be configured even at this scale. Used surgically
# for shared, non-personalized query results (HomeView's section picks,
# ArticleDetailView's related-articles/structured-data) — never for
# anything that varies by request.user, to avoid caching one visitor's
# subscription-gated view of a page for everyone else. See articles/views.py.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache_table',
        'TIMEOUT': 300,  # 5 minutes — short enough that a publish/unpublish is never stale for long
    },
}


# Journal branding (see ARCHITECTURE.md §10.1)
JOURNAL_NAME = os.environ.get('JOURNAL_NAME', 'Health Lens')
JOURNAL_TAGLINE = os.environ.get('JOURNAL_TAGLINE', 'Illuminating Health Research')
JOURNAL_ISSN = os.environ.get('JOURNAL_ISSN', '0000-0000')
JOURNAL_PUBLISHER = os.environ.get('JOURNAL_PUBLISHER', 'Health Lens Publishing')
JOURNAL_CONTACT_EMAIL = os.environ.get('JOURNAL_CONTACT_EMAIL', 'editors@ajnahealthlens.example')


# Cloudflare Turnstile (CAPTCHA) — pitches app, story-pitch submission
# (August 2026: opened to any authenticated account, not just verified
# authors, so a real bot-mitigation layer matters here now). Keys are added
# later; pitches/captcha.py treats a blank TURNSTILE_SECRET_KEY as "not
# configured yet" and skips verification (never blocks submissions) rather
# than failing every request until real keys are set.
TURNSTILE_SITE_KEY = os.environ.get('TURNSTILE_SITE_KEY', '')
TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY', '')


# File upload limits (see ARCHITECTURE.md §7.1)
MANUSCRIPT_MAX_UPLOAD_SIZE_MB = 50
CV_MAX_UPLOAD_SIZE_MB = 10
PROFILE_PHOTO_MAX_UPLOAD_SIZE_MB = 5
ISSUE_COVER_MAX_UPLOAD_SIZE_MB = 10
ARTICLE_PDF_MAX_UPLOAD_SIZE_MB = 100
ARTICLE_IMAGE_MAX_UPLOAD_SIZE_MB = 10
AD_IMAGE_MAX_UPLOAD_SIZE_MB = 5


# Async task queue (Django-Q2) — used for bulk newsletter sends so a
# "compose & send" submit doesn't block the request while it emails every
# subscriber. ORM broker: no Redis/RabbitMQ to deploy, just a DB table,
# which fits this project's MySQL-only footprint. Run a worker with
# `python manage.py qcluster` (see ARCHITECTURE.md §9 for the deployment note).
Q_CLUSTER = {
    'name': 'ajna_health_lens',
    'orm': 'default',
    'workers': 2,
    'timeout': 90,
    'retry': 120,
    'sync': env_bool('Q_CLUSTER_SYNC', False),
}
