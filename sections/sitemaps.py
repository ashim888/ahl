from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Section


class SectionSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        # Matches SectionDetailView.get_queryset() — a link-override section
        # (Training, Issues) has no landing page of its own, so it has
        # nothing to list here; every other active section (top-level or
        # child) does, regardless of depth.
        return Section.objects.filter(is_active=True, link_url_name='').order_by('slug')

    def lastmod(self, item):
        return item.updated_at

    def location(self, item):
        return reverse('sections:section_detail', args=[item.slug])
