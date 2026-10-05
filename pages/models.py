from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.urls import reverse

from articles.sanitize import sanitize_page_html


class SitePage(models.Model):
    """The site's standing pages readers and payment providers expect —
    Terms, Privacy, Refund policy. One row each (seeded by migration as
    unpublished drafts); senior staff edit them at /manage/pages/. A page
    that isn't published is a 404 to the public and isn't linked anywhere.
    """

    class Slug(models.TextChoices):
        TERMS = 'terms', 'Terms of use'
        PRIVACY = 'privacy', 'Privacy policy'
        REFUNDS = 'refund-policy', 'Refund policy'

    slug = models.SlugField(max_length=50, unique=True, choices=Slug.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    is_published = models.BooleanField(
        default=False, help_text='Untick to take the page down. Unpublished pages are 404 to readers and not linked.',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse({
            self.Slug.TERMS: 'pages:terms', self.Slug.PRIVACY: 'pages:privacy', self.Slug.REFUNDS: 'pages:refunds',
        }[self.slug])

    def save(self, *args, **kwargs):
        # Article allow-list minus scripts — these pages never need code.
        for field in ('body', 'body_en', 'body_ne'):
            if getattr(self, field, None):
                setattr(self, field, sanitize_page_html(getattr(self, field)))
        super().save(*args, **kwargs)
        cache.delete(PUBLISHED_CACHE_KEY)


PUBLISHED_CACHE_KEY = 'pages:published'


def published_pages():
    """Published pages in a fixed order, for the footer and checkout — on
    every page view, so cached (cleared by SitePage.save)."""
    def load():
        order = [choice for choice, _ in SitePage.Slug.choices]
        pages = {page.slug: page for page in SitePage.objects.filter(is_published=True)}
        return [pages[slug] for slug in order if slug in pages]

    return cache.get_or_set(PUBLISHED_CACHE_KEY, load, 600)
