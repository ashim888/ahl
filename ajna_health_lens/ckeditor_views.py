import os
import uuid

from django.core.files.storage import FileSystemStorage
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ckeditor_5.views import upload_file

from users.decorators import role_required
from users.models import User


class InlineImageStorage(FileSystemStorage):
    """Where images inserted into article text are stored (the
    CKEDITOR_5_FILE_STORAGE setting): articles/inline/<year>/<month>/ under
    MEDIA_ROOT with a random name, instead of the package default (the media
    root, under the uploader's own filename) — no clashes, and no private
    filenames ("IMG_2231 patient.jpg") in public URLs. The package has
    already checked the extension and that it's a real image by now.
    """

    def save(self, name, content, max_length=None):
        extension = os.path.splitext(name)[1].lower()[:10]
        name = f"articles/inline/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex[:16]}{extension}"
        return super().save(name, content, max_length=max_length)


def _upload_file(request):
    """The package view reads request.FILES['upload'] before validating, so
    a POST without a file was a 500; answer it with CKEditor's error shape."""
    if 'upload' not in request.FILES:
        return JsonResponse({'error': {'message': 'Choose an image to upload.'}}, status=400)
    return upload_file(request)


# Wraps the package's own upload view with this project's RBAC instead of
# relying on CKEDITOR_5_FILE_UPLOAD_PERMISSION (see the setting's comment in
# settings.py for why neither of its two built-in modes fits here). This is
# registered under the exact view name (ck_editor_5_upload_file) the widget
# already reverses, in place of the package's own urls.py.
ckeditor5_upload_file = role_required(*User.EDITORIAL_ROLES)(require_POST(_upload_file))
