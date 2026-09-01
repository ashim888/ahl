from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


class Section(models.Model):
    """Two-level subject-taxonomy nav: a top-level Section (parent=None)
    groups child Sections, and Article.section (see articles/models.py)
    assigns an article to either level. This is independent of
    Article.article_type (a flat format enum — Original Research, Editorial,
    etc.) and Keyword (a flat, non-hierarchical tag) — a new, additive
    subject taxonomy, not a replacement for either.

    `name` is translated per-language via django-modeltranslation (see
    sections/translation.py) — the primary-nav labels are the one thing on
    this site that's actually bilingual today; everything else (article
    content, most UI copy) stays single-language for now.
    """

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children',
        help_text='Leave blank for a top-level nav entry. Only two levels are supported — a '
                   'sub-section cannot itself have children.',
    )
    order = models.IntegerField(default=0, help_text='Display order in the navigation.')
    is_active = models.BooleanField(
        default=True, help_text='Inactive sections are hidden from the public nav but not deleted.',
    )
    link_url_name = models.CharField(
        max_length=100, blank=True,
        help_text='Set only on a top-level entry that should link straight to an existing '
                   'feature\'s own page (e.g. "training:course_list") instead of a Section '
                   'landing page — lets a distinct site feature (Training, Issues) sit in the '
                   'same orderable nav list as a real content section. Leave blank for a normal '
                   'content section.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def clean(self):
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError('A section cannot be its own parent.')
            if self.parent.parent_id:
                raise ValidationError('Sections only support two levels — a sub-section cannot itself have children.')
            if self.link_url_name:
                raise ValidationError('A link override only makes sense on a top-level section, not a sub-section.')
        if self.link_url_name and self.pk and self.children.exists():
            raise ValidationError("A section with a link override can't have sub-sections.")

    @property
    def nav_url(self):
        """Where this nav entry actually points — an existing feature's own
        page for a link-override section (Training, Issues), otherwise this
        section's own landing page.
        """
        if self.link_url_name:
            return reverse(self.link_url_name)
        return reverse('sections:section_detail', args=[self.slug])
