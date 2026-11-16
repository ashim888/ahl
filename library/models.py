"""The digital health library (vision Objective 7, Ajna_vision.docx): research
papers, policy documents, government reports, guidelines, training material,
presentations, datasets and reference resources, in one searchable place.

A resource is either a file uploaded here or a link to where it's officially
hosted (e.g. a report on the MoHP website): linking keeps the original source
authoritative and avoids re-hosting documents we don't own. Everything in the
library is free to read; that's the point of it.

Topics reuse articles.Keyword, so /topics/<slug>/ and the library share one
vocabulary.
"""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .validators import library_file_extension_validator, validate_library_file_size
from ajna_health_lens.validators import validate_document_content


class Resource(models.Model):
    class ResourceType(models.TextChoices):
        RESEARCH_PAPER = 'research_paper', _('Research paper')
        POLICY_DOCUMENT = 'policy_document', _('Policy document')
        GOVERNMENT_REPORT = 'government_report', _('Government report')
        GUIDELINE = 'guideline', _('Guideline or protocol')
        TRAINING_MATERIAL = 'training_material', _('Training material')
        PRESENTATION = 'presentation', _('Presentation')
        DATASET = 'dataset', _('Data')
        REFERENCE = 'reference', _('Reference resource')

    class Language(models.TextChoices):
        NEPALI = 'ne', _('Nepali')
        ENGLISH = 'en', _('English')
        BOTH = 'both', _('Nepali and English')

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True, allow_unicode=True)
    resource_type = models.CharField(max_length=30, choices=ResourceType.choices)
    summary = models.TextField(
        help_text='In plain language: what this is, who it is for and why it matters. 2–4 sentences.',
    )
    source = models.CharField(
        max_length=200, blank=True,
        help_text='Who published it, e.g. "Ministry of Health and Population" or "WHO".',
    )
    year = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Year published (AD), e.g. 2024.',
    )
    language = models.CharField(max_length=4, choices=Language.choices, default=Language.NEPALI)
    file = models.FileField(
        upload_to='library/%Y/', blank=True,
        validators=[library_file_extension_validator, validate_library_file_size, validate_document_content],
        help_text=f'PDF, Word, PowerPoint, Excel or CSV, up to {settings.LIBRARY_MAX_UPLOAD_SIZE_MB} MB.',
    )
    external_url = models.URLField(
        max_length=500, blank=True,
        help_text='Or a link to where it is officially published. Use one or the other.',
    )
    # Recorded on save so listing pages never touch the disk.
    file_size = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    keyword_tags = models.ManyToManyField('articles.Keyword', blank=True, related_name='library_resources')
    related_articles = models.ManyToManyField('articles.Article', blank=True, related_name='library_resources')
    is_published = models.BooleanField(default=False)
    download_count = models.PositiveIntegerField(default=0, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['is_published', 'resource_type'])]

    def __str__(self):
        return self.title

    def clean(self):
        if not self.file and not self.external_url:
            raise ValidationError(_('Upload a file or give a link to where it is published.'))
        if self.file and self.external_url:
            raise ValidationError(_('Use either an uploaded file or a link, not both.'))

    def save(self, *args, **kwargs):
        if not self.slug:
            from articles.slugs import suggest_slug

            base = suggest_slug(self.title) or 'resource'
            slug, n = base, 2
            while Resource.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        if self.file:
            try:
                self.file_size = self.file.size
            except (OSError, ValueError):
                pass
        else:
            self.file_size = None
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('library:resource_detail', args=[self.slug])

    @property
    def file_format(self):
        """'PDF', 'DOCX'… for an upload; '' for a link."""
        if not self.file:
            return ''
        return os.path.splitext(self.file.name)[1].lstrip('.').upper()

    @property
    def is_link(self):
        return not self.file and bool(self.external_url)

    @property
    def link_host(self):
        """'mohp.gov.np' — shown so readers know where a link goes."""
        from urllib.parse import urlparse

        host = urlparse(self.external_url).netloc.lower() if self.external_url else ''
        return host.removeprefix('www.')
