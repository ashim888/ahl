from django.db import models

from .validators import cover_image_extension_validator, validate_cover_image_size


class Issue(models.Model):
    """A journal volume/number. Articles are attached via Article.issue (FK) —
    accessible here as `issue.articles.all()` through that FK's related_name.
    """

    volume = models.IntegerField()
    number = models.IntegerField()
    title = models.CharField(max_length=255, null=True, blank=True)
    cover_image = models.ImageField(
        upload_to='covers/', null=True, blank=True,
        validators=[cover_image_extension_validator, validate_cover_image_size],
        help_text='JPG or PNG, up to 10 MB.',
    )
    publication_date = models.DateField(null=True, blank=True)
    is_published = models.BooleanField(default=False)
    editorial_note = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ('volume', 'number')
        ordering = ['-volume', '-number']

    def __str__(self):
        return f'Vol. {self.volume}, No. {self.number}' + (f' — {self.title}' if self.title else '')
