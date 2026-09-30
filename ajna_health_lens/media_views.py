"""/protected-media/<path> — the only way private uploads are served (see
ajna_health_lens/storage.py). Every request is checked against the record
that owns the file; anything else is a 404, so the URL reveals nothing.
"""
import mimetypes
import os

from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404
from django.shortcuts import redirect

from users.models import User

from .storage import private_storage


def _allowed(request, path):
    """(allowed, redirect_to) for one private file."""
    from articles.models import Article
    from articles.views import pdf_is_accessible

    article = Article.objects.filter(pdf_file=path).first()
    if article is not None:
        if pdf_is_accessible(request, article):
            return True, None
        # A reader who isn't entitled lands on the article (and its paywall).
        if article.status == Article.Status.PUBLISHED:
            return False, article.get_absolute_url()
        return False, None

    owner = User.objects.filter(cv_file=path).first()
    if owner is not None:
        user = request.user
        return user.is_authenticated and (user.pk == owner.pk or user.role in User.EDITORIAL_ROLES), None
    return False, None


def protected_media(request, path):
    allowed, redirect_to = _allowed(request, path)
    if not allowed:
        if redirect_to:
            return redirect(redirect_to)
        raise Http404
    storage = private_storage()
    try:
        handle = storage.open(path, 'rb')
    except (FileNotFoundError, SuspiciousFileOperation):
        raise Http404
    content_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    response = FileResponse(handle, content_type=content_type, filename=os.path.basename(path))
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
