from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from issues.models import Issue

from .models import Article


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
    'pages': StaticViewSitemap,
}
