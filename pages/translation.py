from modeltranslation.translator import TranslationOptions, register

from .models import SitePage


@register(SitePage)
class SitePageTranslationOptions(TranslationOptions):
    # Nepali is optional: an empty Nepali field falls back to English.
    fields = ('title', 'body')
