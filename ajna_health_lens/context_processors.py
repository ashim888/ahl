from django.conf import settings
from django.db import models
from django.templatetags.static import static
from django.urls import reverse


def journal_settings(request):
    from issues.models import Issue  # local import: avoids a project->app import at module load time

    from articles.seo import sitewide_structured_data
    from sections.models import Section

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
        # Primary public nav — top-level sections (Journal, Policy & Economy,
        # etc., plus Training/Issues as link-override entries) with their
        # children prefetched, so templates/base.html's nav loop never
        # issues a query per section. Unused on /manage/ pages (they extend
        # admin_dashboard/base.html instead) but this context processor
        # already runs unconditionally on every request (see `latest_issue`
        # above) — same existing tradeoff, not a new one.
        'nav_sections': Section.objects.filter(parent__isnull=True, is_active=True).order_by('order', 'name').prefetch_related(
            models.Prefetch('children', queryset=Section.objects.filter(is_active=True).order_by('order', 'name')),
        ),
    }
