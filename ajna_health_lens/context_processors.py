from django.conf import settings
from django.templatetags.static import static


def journal_settings(request):
    from issues.models import Issue  # local import: avoids a project->app import at module load time

    return {
        'JOURNAL_NAME': settings.JOURNAL_NAME,
        'JOURNAL_TAGLINE': settings.JOURNAL_TAGLINE,
        'JOURNAL_ISSN': settings.JOURNAL_ISSN,
        'JOURNAL_PUBLISHER': settings.JOURNAL_PUBLISHER,
        'JOURNAL_CONTACT_EMAIL': settings.JOURNAL_CONTACT_EMAIL,
        # -created_at, not -publication_date — an issue's publication_date
        # is optional (unlike Article.publication_date, nothing stamps it
        # automatically), so it's not a reliable "latest" ordering on its own.
        'latest_issue': Issue.objects.filter(is_published=True).order_by('-created_at').first(),
        # Fallback og:image/twitter:image for pages that don't set their own
        # meta_image_url (see templates/base.html) — Open Graph requires an
        # absolute URL, not a relative /static/ path.
        'default_og_image_url': request.build_absolute_uri(static('images/logo.png')),
    }
