"""Translatable strings that don't appear as literals in this project's own
templates or code, listed here so `makemessages` extracts them into
locale/*/django.po instead of marking their entries obsolete.

- django_comments_xtd's email subjects and comment-form labels/placeholders:
  hard-coded gettext() calls inside the package, which makemessages never
  scans (it skips site-packages). Our locale files override them — English
  subjects reworded, Nepali labels added.
- The journal tagline: a setting (JOURNAL_TAGLINE) translated at render time
  with {% trans JOURNAL_TAGLINE %} in base.html; this is its default value.

Nothing imports this module; it exists only for extraction.
"""
from django.utils.translation import gettext_noop

EXTRA_STRINGS = [
    # django_comments_xtd — views.py email subjects
    gettext_noop('comment confirmation request'),
    gettext_noop('new comment posted'),
    # django_comments_xtd — forms.py
    gettext_noop('Notify me about follow-up comments'),
    gettext_noop('Name'),
    gettext_noop('name'),
    gettext_noop('Mail'),
    gettext_noop('Required for comment verification'),
    gettext_noop('mail address'),
    gettext_noop('Your comment'),
    # settings.JOURNAL_TAGLINE default
    gettext_noop('Illuminating Health Research'),
]
