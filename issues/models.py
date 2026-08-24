from django.db import models

from .validators import cover_image_extension_validator, validate_cover_image_size


class Issue(models.Model):
    """A curated group of related articles — a "story trail"/series for the
    news site (e.g. ongoing coverage of one topic), not a formal academic
    journal volume/issue — OJS owns that numbering entirely on its own and
    this platform doesn't replicate it. Articles are attached via
    Article.issue (FK) — accessible here as `issue.articles.all()` through
    that FK's related_name.
    """

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    cover_image = models.ImageField(
        upload_to='covers/', null=True, blank=True,
        validators=[cover_image_extension_validator, validate_cover_image_size],
        help_text='JPG or PNG, up to 10 MB.',
    )
    publication_date = models.DateField(
        null=True, blank=True, help_text='Optional — shown on the issue page if set.',
    )
    is_published = models.BooleanField(default=False)
    editorial_note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
