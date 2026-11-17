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

# Paths under /library/ that aren't documents.
RESERVED_SLUGS = {'glossary'}


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
    # Plain a–z only: the URL pattern (<slug:slug>) can't route anything else,
    # so a Nepali slug typed in admin would break every page that links to it.
    # Generated slugs are already romanized (articles/slugs.py).
    slug = models.SlugField(max_length=255, unique=True, blank=True)
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
            if base in RESERVED_SLUGS:  # /library/glossary/ is the glossary, not a document
                base = f'{base}-document'
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


class GlossaryTerm(models.Model):
    """A medical or public-health term explained in plain language (vision
    Objective 7, "reference resources and glossaries"; Pillar 3, simple and
    actionable language). Bilingual by nature: a term usually has a Nepali
    and an English name, and readers search by either."""

    term_ne = models.CharField('Term (Nepali)', max_length=150, blank=True)
    term_en = models.CharField('Term (English)', max_length=150, blank=True)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    also_called = models.CharField(
        max_length=255, blank=True,
        help_text='Other names and abbreviations, separated by commas, e.g. "Sugar disease, DM".',
    )
    definition_ne = models.TextField(
        'Definition (Nepali)', blank=True,
        help_text='Plain language a non-specialist understands: what it is, and why it matters. 1–3 sentences.',
    )
    definition_en = models.TextField('Definition (English)', blank=True)
    keyword_tags = models.ManyToManyField('articles.Keyword', blank=True, related_name='glossary_terms')
    related_terms = models.ManyToManyField('self', blank=True, symmetrical=True)
    is_published = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['term_ne', 'term_en']

    def __str__(self):
        return self.display_name

    def clean(self):
        if not self.term_ne.strip() and not self.term_en.strip():
            raise ValidationError(_('Give the term in Nepali, English or both.'))
        if not self.definition_ne.strip() and not self.definition_en.strip():
            raise ValidationError(_('Write a definition in Nepali, English or both.'))

    def save(self, *args, **kwargs):
        if not self.slug:
            from articles.slugs import suggest_slug

            from django.utils.text import slugify

            # suggest_slug drops filler words, so "WHO" alone would come out empty.
            base = suggest_slug(self.term_en or self.term_ne) or slugify(self.term_en) or 'term'
            slug, n = base, 2
            while GlossaryTerm.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('library:glossary_detail', args=[self.slug])

    @property
    def display_name(self):
        """'मधुमेह (Diabetes)', or whichever name there is."""
        if self.term_ne and self.term_en:
            return f'{self.term_ne} ({self.term_en})'
        return self.term_ne or self.term_en

    @property
    def primary_term(self):
        return self.term_ne or self.term_en

    @property
    def aliases(self):
        return [a.strip() for a in self.also_called.split(',') if a.strip()]

    @property
    def names(self):
        """Every name the term goes by: for search and for finding articles."""
        return [n for n in [self.term_ne, self.term_en, *self.aliases] if n]

    def definition_for(self, language_code):
        """The definition in the reader's language, else the other one."""
        if language_code == 'en':
            return self.definition_en or self.definition_ne
        return self.definition_ne or self.definition_en

    @property
    def index_letter(self):
        """First letter for the A–Z index: Devanagari consonant/vowel or A–Z."""
        first = (self.primary_term or '#')[:1].upper()
        return first if first.isalpha() else '#'
