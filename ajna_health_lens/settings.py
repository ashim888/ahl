"""
Django settings for ajna_health_lens project.

See CLAUDE.md and ARCHITECTURE.md for the full spec this file implements.
"""

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


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Ajna Health Lens apps
    'users',
    'articles',
    'submissions',   # dormant — see ARCHITECTURE.md §4.4 / ROADMAP.md "Scope Pivot"
    'peer_review',   # dormant — see ARCHITECTURE.md §4.4 / ROADMAP.md "Scope Pivot"
    'issues',
    'admin_custom',
    'training',
    'editorial_board',
    'billing',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

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

TIME_ZONE = 'Asia/Kathmandu'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

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


# Journal branding (see ARCHITECTURE.md §10.1)
JOURNAL_NAME = os.environ.get('JOURNAL_NAME', 'Ajna Health Lens')
JOURNAL_TAGLINE = os.environ.get('JOURNAL_TAGLINE', 'Illuminating Health Research')
JOURNAL_ISSN = os.environ.get('JOURNAL_ISSN', '0000-0000')
JOURNAL_PUBLISHER = os.environ.get('JOURNAL_PUBLISHER', 'Ajna Health Lens Publishing')
JOURNAL_CONTACT_EMAIL = os.environ.get('JOURNAL_CONTACT_EMAIL', 'editors@ajnahealthlens.example')


# File upload limits (see ARCHITECTURE.md §7.1)
MANUSCRIPT_MAX_UPLOAD_SIZE_MB = 50
CV_MAX_UPLOAD_SIZE_MB = 10
PROFILE_PHOTO_MAX_UPLOAD_SIZE_MB = 5
ISSUE_COVER_MAX_UPLOAD_SIZE_MB = 10
ARTICLE_PDF_MAX_UPLOAD_SIZE_MB = 100
ARTICLE_IMAGE_MAX_UPLOAD_SIZE_MB = 10
