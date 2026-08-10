from django.conf import settings


def journal_settings(request):
    return {
        'JOURNAL_NAME': settings.JOURNAL_NAME,
        'JOURNAL_TAGLINE': settings.JOURNAL_TAGLINE,
        'JOURNAL_ISSN': settings.JOURNAL_ISSN,
        'JOURNAL_PUBLISHER': settings.JOURNAL_PUBLISHER,
    }
