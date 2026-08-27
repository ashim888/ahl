from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse


def journal_settings(request):
    from issues.models import Issue  # local import: avoids a project->app import at module load time

    from articles.seo import sitewide_structured_data

    default_og_image_url = request.build_absolute_uri(static('images/logo.png'))

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
        'default_og_image_url': default_og_image_url,
        # Fallback canonical URL for any page that doesn't set its own
        # canonical_url — request.path only, deliberately dropping the
        # querystring. Without this, base.html's old fallback
        # (request.build_absolute_uri with no args) self-canonicalized every
        # filtered/paginated/searched URL variant (?page=2, ?type=x, ?q=y)
        # as its own indexable page, splitting ranking signal across
        # near-duplicate URLs instead of consolidating it on the clean one.
        'default_canonical_url': request.build_absolute_uri(request.path),
        # NewsMediaOrganization + WebSite/SearchAction JSON-LD, sitewide (see
        # templates/base.html) — was only emitted per-article (NewsArticle);
        # nothing told Google this site *is* a publication with a search box.
        'sitewide_structured_data_json': sitewide_structured_data(
            journal_name=settings.JOURNAL_NAME, logo_url=default_og_image_url,
            site_url=request.build_absolute_uri('/'), search_url=request.build_absolute_uri(reverse('articles:search')),
        ),
    }
