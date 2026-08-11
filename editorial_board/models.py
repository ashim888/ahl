from django.db import models


class EditorialBoardMember(models.Model):
    """Public-facing board member bio. Deliberately independent of `User` —
    board members are public content, not necessarily site accounts.
    """

    name = models.CharField(max_length=255)
    role_title = models.CharField(
        max_length=255,
        help_text='e.g. "Editor-in-Chief", "Associate Editor, Cardiology".',
    )
    affiliation = models.CharField(max_length=255, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to='editorial_board/', null=True, blank=True)
    order = models.IntegerField(default=0, help_text='Display order on the public page.')
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive members are hidden from the public page but not deleted.',
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
