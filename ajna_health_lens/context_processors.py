from django.conf import settings


def journal_settings(request):
    from issues.models import Issue  # local import: avoids a project->app import at module load time

    return {
        'JOURNAL_NAME': settings.JOURNAL_NAME,
        'JOURNAL_TAGLINE': settings.JOURNAL_TAGLINE,
        'JOURNAL_ISSN': settings.JOURNAL_ISSN,
        'JOURNAL_PUBLISHER': settings.JOURNAL_PUBLISHER,
        'JOURNAL_CONTACT_EMAIL': settings.JOURNAL_CONTACT_EMAIL,
        'latest_issue': Issue.objects.filter(is_published=True).order_by('-publication_date').first(),
    }
