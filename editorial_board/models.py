from django.conf import settings
from django.db import models

from .validators import photo_extension_validator, validate_photo_size


class EditorialBoardMember(models.Model):
    """Public-facing board member bio. Independent of `User` by default —
    board members are public content, not necessarily site accounts — but
    `user` optionally links a member to their actual account when the same
    person also writes/edits content here, so the public site can cross-link
    their board bio and their author byline page.
    """

    name = models.CharField(max_length=255)
    role_title = models.CharField(
        max_length=255,
        help_text='e.g. "Editor-in-Chief", "Associate Editor, Cardiology".',
    )
    affiliation = models.CharField(max_length=255, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    photo = models.ImageField(
        upload_to='editorial_board/', null=True, blank=True,
        validators=[photo_extension_validator, validate_photo_size],
        help_text='JPG or PNG, up to 5 MB.',
    )
    order = models.IntegerField(default=0, help_text='Display order on the public page.')
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive members are hidden from the public page but not deleted.',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='board_memberships',
        help_text="Optional — link to this person's site account if they also have one, "
                  'to cross-link their board bio with their author byline page.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.name} ({self.role_title})'

    @property
    def last_name_initial(self):
        """Last word of `name`'s first letter, for the avatar badge — e.g.
        "Dr. Sunita Rai" -> "R". A plain `|last` template filter would return
        the last *character* of the string instead, which is wrong.
        """
        parts = self.name.split()
        return parts[-1][0].upper() if parts else '?'
