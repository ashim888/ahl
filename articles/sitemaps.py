import datetime

from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.utils import timezone

from issues.models import Issue
from sections.sitemaps import SectionSitemap

from .models import Article


class NewsArticleSitemap(Sitemap):
    """Google News Sitemap — a separate protocol (the `news:` namespace,
    see templates/sitemaps/news_sitemap.xml) from the regular ArticleSitemap
    below, and the thing that actually gates eligibility for Google News/
    Discover surfacing. Deliberately NOT a full archive: Google's spec caps
    it to articles published in roughly the last 2 days — this sitemap is
    meant to say "here's what's new", not list every article ever published
    (that's ArticleSitemap's job, for regular search indexing).
    """

    # Google's documented cap for a news sitemap (also the general per-
    # sitemap URL limit) — effectively a no-op at this site's current
    # volume, but keeps the guarantee explicit rather than assumed.
    limit = 1000

    def items(self):
        # publication_date is a plain DateField (no time-of-day), so "2 days"
        # is the closest approximation of Google's ~48-hour window this data
        # can express — see the model's help_text in articles/models.py.
        cutoff = timezone.localdate() - datetime.timedelta(days=2)
        return Article.objects.filter(
            status=Article.Status.PUBLISHED, publication_date__gte=cutoff,
        ).order_by('-publication_date')

    def location(self, item):
        return reverse('articles:article_detail', args=[item.slug])


class ArticleSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.8

    def items(self):
        return Article.objects.filter(status=Article.Status.PUBLISHED).order_by('-publication_date')

    def lastmod(self, item):
        return item.updated_at

    def location(self, item):
        return reverse('articles:article_detail', args=[item.slug])


class IssueSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        return Issue.objects.filter(is_published=True).order_by('-created_at')

    def lastmod(self, item):
        return item.created_at

    def location(self, item):
        return reverse('issues:issue_detail', args=[item.slug])


class StaticViewSitemap(Sitemap):
    """Low-churn, high-value pages that don't have their own model."""

    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return ['articles:home', 'articles:article_list', 'issues:issue_list', 'training:course_list', 'billing:plan_browse']

    def location(self, item):
        return reverse(item)


sitemaps = {
    'articles': ArticleSitemap,
    'issues': IssueSitemap,
    'sections': SectionSitemap,
    'pages': StaticViewSitemap,
}
