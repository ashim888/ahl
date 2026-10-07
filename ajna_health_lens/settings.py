"""
Django settings for ajna_health_lens project.

See CLAUDE.md and ARCHITECTURE.md for the full spec this file implements.
"""

import datetime
import os
import re
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


_INSECURE_DEFAULT_SECRET_KEY = 'django-insecure-dev-only-change-me'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', _INSECURE_DEFAULT_SECRET_KEY)

# SECURITY WARNING: don't run with debug turned on in production!
# Off unless .env says DEBUG=True (local development). Defaulting to on
# meant a server whose .env missed the line showed full debug error pages
# (code, settings, SQL) to anyone who triggered an error.
DEBUG = env_bool('DEBUG', False)
# Staging only: lets `check --deploy` (deploy.sh) pass with DEBUG on (ajna.E004).
ALLOW_DEBUG_DEPLOY = env_bool('ALLOW_DEBUG_DEPLOY', False)

# The fallback above exists only so a fresh dev checkout runs with zero
# setup — silently reusing it in production would mean every deployment
# that forgets to set SECRET_KEY shares one publicly-visible key (it's
# committed to this file's git history), defeating session/CSRF-token
# signing and password-reset tokens. Fail loudly instead of booting insecure.
# The .env.example placeholder is refused for the same reason.
if not DEBUG and SECRET_KEY in (_INSECURE_DEFAULT_SECRET_KEY, 'change-me-to-a-random-secret-key'):
    raise ImproperlyConfigured(
        'SECRET_KEY is not set. Set a real, random SECRET_KEY in the environment before running with DEBUG=False.',
    )

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
# Content Security Policy (ajna_health_lens/middleware.py): where scripts,
# frames, images and connections may come from. 'unsafe-inline' is needed
# for the templates' inline scripts and editors' chart code; the host lists
# still stop an injected <script src> or data leak to any other site.
# Violations are logged via /csp-report/. CSP_REPORT_ONLY=True only reports.
CSP_REPORT_ONLY = env_bool('CSP_REPORT_ONLY', False)
CSP_DIRECTIVES = {
    'default-src': ["'self'"],
    'script-src': ["'self'", "'unsafe-inline'", 'https://www.googletagmanager.com', 'https://d3js.org',
                   'https://cdn.jsdelivr.net', 'https://cdnjs.cloudflare.com', 'https://challenges.cloudflare.com'],
    'style-src': ["'self'", "'unsafe-inline'", 'https://cdn.jsdelivr.net'],
    'img-src': ["'self'", 'data:', 'blob:', 'https:'],
    'font-src': ["'self'", 'data:'],
    'connect-src': ["'self'", 'https://*.google-analytics.com', 'https://*.analytics.google.com',
                    'https://*.googletagmanager.com', 'wss://*.fonepay.com', 'https://challenges.cloudflare.com'],
    'frame-src': ['https://www.youtube-nocookie.com', 'https://www.youtube.com', 'https://player.vimeo.com',
                  'https://www.dailymotion.com', 'https://open.spotify.com', 'https://challenges.cloudflare.com'],
    'media-src': ["'self'"],
    'object-src': ["'none'"],
    'base-uri': ["'self'"],
    'form-action': ["'self'"],
    'frame-ancestors': ["'none'"],
}
# Browser features nothing on the site uses.
PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(), usb=(), interest-cohort=()'
# A friendly "please try again" page instead of Django's bare CSRF 403.
CSRF_FAILURE_VIEW = 'ajna_health_lens.error_views.csrf_failure'


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
    # submissions/peer_review (academic manuscript submission + peer review)
    # were removed September 2026 — OJS owns that externally, and pitches
    # (below) never depended on them. See CLAUDE.md's SCOPE NOTE and
    # ROADMAP.md "Scope Pivot" / the Risk Register.
    'users',
    'articles',
    'issues',
    'sections',
    'admin_custom',
    'training',
    'editorial_board',
    'billing',
    'newsletter',
    'ads',
    'pitches',
    'pages',
    # Two-step sign-in (TOTP authenticator apps + backup codes) for staff — users/two_factor.py.
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Emails MANAGERS (= ADMINS) when a page on this site links to a URL that
    # 404s — a broken internal link. Outside links and bots are ignored (see
    # IGNORABLE_404_URLS). Must come before LocaleMiddleware (Django docs).
    # Only links on our own pages — see ajna_health_lens/middleware.py.
    'ajna_health_lens.middleware.InternalBrokenLinkEmailsMiddleware',
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
    # Staff must set up / pass two-step sign-in before using the site (users/two_factor.py).
    # (django-otp's own OTPMiddleware is deliberately NOT used: it sets
    # request.user.is_verified to a function, which collides with our
    # User.is_verified field and breaks saving the signed-in user.)
    'users.two_factor.StaffTwoFactorMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # django-axes' docs require this to be the last middleware in the list —
    # it reads a lockout flag AxesStandaloneBackend leaves on the request
    # (see AUTHENTICATION_BACKENDS/AXES_* below) and, only then, rewrites the
    # response into a 429. Debug Toolbar inserts itself at index 1 below,
    # which doesn't disturb this middleware staying last.
    # Content-Security-Policy + Permissions-Policy headers (settings CSP_*).
    'ajna_health_lens.middleware.SecurityHeadersMiddleware',
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
            # Search (articles/search.py): the ngram FULLTEXT index on titles
            # must be built without MySQL's stopword list, or every 2-letter
            # chunk containing "a", "is"… is dropped and words like "malaria"
            # never match. MySQL rebuilds FULLTEXT indexes whenever a migration
            # rebuilds the table (e.g. adds a column), using the session's
            # setting — so every connection, including `migrate`, keeps it off.
            'init_command': 'SET SESSION innodb_ft_enable_stopword=OFF',
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
# Uploads that must not be public — article PDFs (paywalled) and CVs
# (personal data). Served only through /protected-media/, which checks
# access on every request (ajna_health_lens/storage.py, media_views.py).
# Must be OUTSIDE anything the web server serves directly.
PRIVATE_MEDIA_ROOT = Path(os.environ.get('PRIVATE_MEDIA_ROOT') or BASE_DIR / 'private_media')
# Where `manage.py quarantine_orphan_media --move` puts uploads nothing
# references any more — out of public reach, not deleted. Not served.
ORPHAN_MEDIA_ROOT = Path(os.environ.get('ORPHAN_MEDIA_ROOT') or BASE_DIR / 'media_orphans')
# Tests save uploads into temporary folders, never the real ones above.
TEST_RUNNER = 'ajna_health_lens.test_runner.IsolatedMediaTestRunner'


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
    # The article/newsletter editor. Every plugin listed here ships in
    # django-ckeditor-5's prebuilt bundle; this only chooses which are on
    # the toolbar and how they behave. Anything whose output needs markup
    # or styles must also be allowed by articles/sanitize.py (it runs on
    # save) and styled for readers in templates/base.html (.prose-article).
    'articles': {
        'toolbar': {
            'items': [
                'heading', '|',
                'bold', 'italic', 'underline', 'strikethrough', 'subscript', 'superscript', 'removeFormat', '|',
                'alignment', '|',
                'bulletedList', 'numberedList', 'outdent', 'indent', '|',
                'link', 'insertImage', 'mediaEmbed', 'insertTable', 'blockQuote', 'horizontalLine', 'specialCharacters', '|',
                'code', 'codeBlock', '|',
                'findAndReplace', 'undo', 'redo', '|', 'sourceEditing',
            ],
            # Wrap onto a second row instead of hiding tools behind "⋮".
            'shouldNotGroupWhenFull': True,
        },
        # Plugins in the bundle this editor must NOT run: Markdown would
        # store Markdown instead of HTML, FullPage would wrap the article
        # in <html>/<body>, and Autosave/Mention/Style/HtmlEmbed aren't used.
        'removePlugins': ['Markdown', 'FullPage', 'Autosave', 'Mention', 'Style', 'HtmlEmbed'],
        # H1 is the headline itself, so the body starts at H2.
        'heading': {
            'options': [
                {'model': 'paragraph', 'title': 'Paragraph', 'class': 'ck-heading_paragraph'},
                {'model': 'heading2', 'view': 'h2', 'title': 'Heading', 'class': 'ck-heading_heading2'},
                {'model': 'heading3', 'view': 'h3', 'title': 'Subheading', 'class': 'ck-heading_heading3'},
                {'model': 'heading4', 'view': 'h4', 'title': 'Minor heading', 'class': 'ck-heading_heading4'},
            ],
        },
        # Stored as style="text-align: ..." (kept by the sanitizer).
        'alignment': {'options': ['left', 'center', 'right', 'justify']},
        # Upload goes to ckeditor5/image_upload/ (editorial roles only, see
        # ajna_health_lens/ckeditor_views.py); "insert via URL" is also offered.
        'image': {
            'toolbar': [
                'imageTextAlternative', 'toggleImageCaption', '|',
                'imageStyle:inline', 'imageStyle:alignLeft', 'imageStyle:alignCenter', 'imageStyle:alignRight', '|',
                'resizeImage', '|', 'linkImage',
            ],
            # No None/null anywhere in this config: django-ckeditor-5 parses it
            # with a JSON reviver that crashes on null (the whole editor then
            # fails to load). CKEditor's "original size" option is normally
            # value null; False works the same (any falsy value = no width).
            'resizeUnit': '%',
            'resizeOptions': [
                {'name': 'resizeImage:original', 'value': False, 'label': 'Original size'},
                {'name': 'resizeImage:50', 'value': '50', 'label': 'Half width'},
                {'name': 'resizeImage:75', 'value': '75', 'label': 'Three quarters'},
                {'name': 'resizeImage:100', 'value': '100', 'label': 'Full width'},
            ],
            'insert': {'integrations': ['upload', 'url']},
        },
        'link': {
            'addTargetToExternalLinks': True,
            'defaultProtocol': 'https://',
        },
        'list': {'properties': {'styles': True, 'startIndex': True, 'reversed': False}},
        # Store the real embed (an <iframe>) rather than a bare <oembed> tag
        # browsers can't display. Only these providers; the sanitizer
        # allows iframes from the same hosts only.
        'mediaEmbed': {
            'previewsInData': True,
            'removeProviders': ['instagram', 'twitter', 'googleMaps', 'flickr', 'facebook'],
        },
        'table': {
            'contentToolbar': ['tableColumn', 'tableRow', 'mergeTableCells', 'toggleTableCaption'],
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
# Images inserted into article text: common web formats only (no SVG, which
# can carry script), each checked by Pillow before it's stored.
CKEDITOR_5_UPLOAD_FILE_TYPES = ['jpg', 'jpeg', 'png', 'gif', 'webp']
CKEDITOR_5_MAX_FILE_SIZE = 5  # MB
CKEDITOR_5_FILE_STORAGE = 'ajna_health_lens.ckeditor_views.InlineImageStorage'

# Uploaded images are resized, stripped of metadata and re-compressed
# before they're stored (ajna_health_lens/images.py).
IMAGE_OPTIMIZE_UPLOADS = env_bool('IMAGE_OPTIMIZE_UPLOADS', True)
IMAGE_MAX_DIMENSION = int(os.environ.get('IMAGE_MAX_DIMENSION', '2400'))
IMAGE_JPEG_QUALITY = int(os.environ.get('IMAGE_JPEG_QUALITY', '82'))


# Reader comments (django-comments-xtd) — threaded comments on articles.
# django.contrib.sites (SITE_ID) is a hard dependency of django_comments;
# its Site row's `domain` is kept in sync with SITE_BASE_URL above by a data
# migration (articles/migrations/0019_sync_site_domain.py) so confirmation/
# follow-up emails link back to the real site instead of the "example.com"
# the sites migration creates by default.
SITE_ID = 1
COMMENTS_APP = 'django_comments_xtd'

# rest_framework is installed only for django_comments_xtd's own comment API
# (see api/views.py), which sets its own permission_classes explicitly on
# every view (AllowAny where it means to be public, IsAuthenticatedOrReadOnly
# elsewhere) — this doesn't change that. It only closes the gap for any DRF
# view added to this project later without setting permission_classes
# itself, which would otherwise silently fall back to DRF's own default of
# AllowAny.
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
}

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
# .env is read once at process start (load_dotenv above) — after changing
# any of these, restart the server; runserver's autoreload doesn't watch .env.
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
# Port 587 → STARTTLS (EMAIL_USE_TLS=True); port 465 → implicit SSL
# (EMAIL_USE_SSL=True, EMAIL_USE_TLS=False). Django refuses both at once.
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
if EMAIL_USE_SSL:
    EMAIL_USE_TLS = False
# Seconds before giving up on an unreachable SMTP server — without it a
# misconfigured host hangs the request (e.g. a comment post) indefinitely.
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '30'))
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@ajnahealthlens.example')


# Error visibility — previously nothing at all: no LOGGING config, no ADMINS,
# no error tracker. Django's own AdminEmailHandler already exists to email
# ADMINS on an unhandled 500, but it's a silent no-op with ADMINS unset
# (django.core.mail.mail_admins() returns immediately if ADMINS is empty) —
# blank by default so dev/CI never tries to send anything; a deployment sets
# ADMIN_EMAILS to actually receive these.
ADMINS = [('Admin', e.strip()) for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()]
MANAGERS = ADMINS
# Bot probes and browser guesses that 404 all day — never worth an email.
IGNORABLE_404_URLS = [
    re.compile(pattern) for pattern in (
        r'\.(php|asp|aspx|jsp|cgi|env|git|bak|sql|ini|log)$', r'^/(wp-|wordpress|phpmyadmin|pma|xmlrpc|cgi-bin|\.well-known/)',
        r'^/(favicon\.ico|apple-touch-icon.*\.png|robots\.txt|ads\.txt|sitemap\.xml\.gz)$',
    )
]
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'},
    },
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {name} {message}', 'style': '{'},
    },
    'handlers': {
        # Always on, not gated to DEBUG (Django's own default console
        # handler for the 'django' logger only fires when DEBUG=True) — a
        # host like cPanel/Passenger (see ARCHITECTURE.md §9.7) captures
        # stdout/stderr to its own log file, so this is the baseline trail
        # even before ADMIN_EMAILS is set.
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
    },
    # Catches this app's own best-effort loggers — ajna_health_lens/mail.py,
    # billing/gateway.py, newsletter/tasks.py (the fault-injection wrappers
    # that log-and-swallow an exception instead of raising, see
    # ROADMAP.md's fault-injection entry) — none of which live under the
    # 'django' logger namespace, so they'd otherwise reach console only via
    # Python's own logging "handler of last resort", never ADMINS.
    'root': {
        'handlers': ['console', 'mail_admins'],
        'level': 'INFO',
    },
    'loggers': {
        # Explicit and propagate=False so a django.request 500 is handled
        # once here, not again via root (it would otherwise double up:
        # Django's own default 'django' logger config always propagates).
        'django': {
            'handlers': ['console', 'mail_admins'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


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


# Raw analytics events (page views, keyword and ad impressions/clicks)
# older than this are deleted daily — see admin_custom/retention.py.
ANALYTICS_RETENTION_DAYS = int(os.environ.get('ANALYTICS_RETENTION_DAYS', '400'))


# Journal branding (see ARCHITECTURE.md §10.1)
JOURNAL_NAME = os.environ.get('JOURNAL_NAME', 'Health Lens')
JOURNAL_TAGLINE = os.environ.get('JOURNAL_TAGLINE', 'Illuminating Health Research')
JOURNAL_ISSN = os.environ.get('JOURNAL_ISSN', '0000-0000')
JOURNAL_PUBLISHER = os.environ.get('JOURNAL_PUBLISHER', 'Health Lens Publishing')
JOURNAL_CONTACT_EMAIL = os.environ.get('JOURNAL_CONTACT_EMAIL', 'editors@ajnahealthlens.com')

# Every price on the site (subscriptions, special articles, training courses,
# revenue dashboards) is shown as "Rs. 1,49,999" — see billing/money.py.
# CURRENCY_CODE is the ISO 4217 code used in structured data (schema.org
# priceCurrency).
CURRENCY_SYMBOL = 'Rs.'
CURRENCY_CODE = 'NPR'

# Payment gateway (billing/gateway.py). "stub" = checkout always succeeds
# with no money moving (development/tests); "fonepay" = real Fonepay
# Checkout (billing/fonepay.py): the reader pays by QR or their bank app and
# access is granted only after the server confirms the payment with Fonepay.
PAYMENT_GATEWAY = os.environ.get('PAYMENT_GATEWAY', 'stub').strip().lower()
# Staging servers only: lets DEBUG=False run with the stub gateway without
# failing the ajna.E003 deploy check (articles/checks.py).
ALLOW_STUB_PAYMENTS = env_bool('ALLOW_STUB_PAYMENTS', False)
# Fonepay merchant credentials — issued by Fonepay; never commit them.
# FONEPAY_API_URL is the base URL *including* the API path, e.g.
# https://dev-external-gateway-new.fonepay.com/merchantThirdparty/api/merchant/third-party/v2
FONEPAY_API_URL = os.environ.get('FONEPAY_API_URL', '').rstrip('/')
FONEPAY_USERNAME = os.environ.get('FONEPAY_USERNAME', '')
FONEPAY_PASSWORD = os.environ.get('FONEPAY_PASSWORD', '')
# Base64 PKCS#8 RSA private key, without the -----BEGIN/END----- lines.
FONEPAY_PRIVATE_KEY = os.environ.get('FONEPAY_PRIVATE_KEY', '')
FONEPAY_TERMINAL_ID = os.environ.get('FONEPAY_TERMINAL_ID', '')
# How long a generated QR stays payable before the reader must start again.
FONEPAY_PAYMENT_TIMEOUT_MINUTES = int(os.environ.get('FONEPAY_PAYMENT_TIMEOUT_MINUTES', '15'))

# Google Analytics — loaded only for readers who accept analytics cookies
# (templates/includes/cookie_consent.html). Empty turns it off entirely.
GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID', 'G-KDLXMLM9WD')
# Name of the cookie that remembers a reader's cookie choice.
COOKIE_CONSENT_COOKIE = 'cookie_consent'

# Error tracking (Sentry) — on only when SENTRY_DSN is set. send_default_pii
# stays False: no emails, IPs or cookies in error reports.
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN, environment=os.environ.get('SENTRY_ENVIRONMENT', 'production'),
        send_default_pii=False, traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0')),
    )
# How old the background worker's last heartbeat may be before /healthz/
# and `check_health` call it down (ajna_health_lens/health.py).
WORKER_HEARTBEAT_MAX_AGE_MINUTES = 15

# Two-step sign-in (users/two_factor.py): every Editor, Editor-in-Chief and
# Admin needs an authenticator app. Only switch off for local development.
STAFF_TWO_FACTOR_REQUIRED = env_bool('STAFF_TWO_FACTOR_REQUIRED', True)
OTP_TOTP_ISSUER = JOURNAL_NAME  # the name shown in the authenticator app

# Off-site backup by email (ajna_health_lens/backups.py): the database,
# encrypted with BACKUP_ENCRYPTION_PASSWORD, emailed nightly to BACKUP_EMAIL.
# Both empty = off. Keep the password OFF this server (password manager).
BACKUP_EMAIL = os.environ.get('BACKUP_EMAIL', '')
BACKUP_ENCRYPTION_PASSWORD = os.environ.get('BACKUP_ENCRYPTION_PASSWORD', '')
BACKUP_EMAIL_MAX_MB = int(os.environ.get('BACKUP_EMAIL_MAX_MB', '20'))

# Billing — every price (plans, special articles, courses) is VAT-exclusive;
# checkout adds VAT_RATE percent on top (billing/money.py vat_breakdown).
VAT_RATE = Decimal(os.environ.get('VAT_RATE', '13'))
# Printed on every receipt (billing/receipt.html). Receipt numbers are
# RECEIPT_PREFIX + a gap-free sequence (billing.models.ReceiptSequence).
BUSINESS_LEGAL_NAME = os.environ.get('BUSINESS_LEGAL_NAME', JOURNAL_NAME)
BUSINESS_PAN = os.environ.get('BUSINESS_PAN', '')
BUSINESS_ADDRESS = os.environ.get('BUSINESS_ADDRESS', '')
RECEIPT_PREFIX = os.environ.get('RECEIPT_PREFIX', 'AHL-')
# Invoice dates: 'both' (AD with BS alongside), 'ad' or 'bs' (billing/nepali.py).
INVOICE_DATE_DISPLAY = os.environ.get('INVOICE_DATE_DISPLAY', 'both').strip().lower()
# Expiry reminder emails go out this many days before a subscription ends
# (and once the day after it has ended) — billing/reminders.py.
SUBSCRIPTION_REMINDER_DAYS = (7, 1)
# A paid subscription can be cancelled by the reader for a full refund within
# this many days of paying (billing.views.subscription_cancel); after that it
# runs to its end date.
SUBSCRIPTION_CANCEL_DAYS = int(os.environ.get('SUBSCRIPTION_CANCEL_DAYS', '3'))


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
