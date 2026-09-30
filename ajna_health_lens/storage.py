"""Private uploads: files that must never be reachable at a public /media/
address — article PDFs (paywalled content) and CVs (personal data).

They live in PRIVATE_MEDIA_ROOT, which nginx/Apache must NOT serve, and
their .url points at /protected-media/<path>, a Django view
(ajna_health_lens/media_views.py) that checks who's asking on every request.
So links, the admin and form file inputs keep working, but a copied or
shared URL is useless to anyone not entitled to the file.
"""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage

PROTECTED_MEDIA_URL = '/protected-media/'


class PrivateMediaStorage(FileSystemStorage):
    def __init__(self, **kwargs):
        super().__init__(base_url=PROTECTED_MEDIA_URL, **kwargs)

    # Read PRIVATE_MEDIA_ROOT on every use (not once at import, as a
    # location passed to __init__ would be), so override_settings in tests
    # and a changed setting both take effect.
    @property
    def base_location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def private_storage():
    """Callable storage for FileField(storage=...) — keeps migrations free
    of a concrete path and reads PRIVATE_MEDIA_ROOT from settings."""
    return PrivateMediaStorage()
