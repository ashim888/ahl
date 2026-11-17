"""/protected-media/<path> — the only way private uploads are served (see
ajna_health_lens/storage.py). Every request is checked against the record
that owns the file; anything else is a 404, so the URL reveals nothing.
"""
import mimetypes
import os
import re

from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect

from users.models import User

from .storage import private_storage


def _allowed(request, path):
    """(allowed, redirect_to) for one private file."""
    from articles.models import Article
    from articles.views import pdf_is_accessible

    article = Article.objects.filter(Q(pdf_file=path) | Q(audio_file=path)).first()
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
    byte_range = _requested_range(request, handle)
    if byte_range == 'unsatisfiable':
        handle.close()
        response = HttpResponse(status=416)
        response['Content-Range'] = f'bytes */{handle.size}'
        return response
    if byte_range:
        # Part of the file: how audio players stream and seek (Safari won't play without it).
        start, end = byte_range
        handle.seek(start)
        response = StreamingHttpResponse(_read(handle, end - start + 1), status=206, content_type=content_type)
        response['Content-Range'] = f'bytes {start}-{end}/{handle.size}'
        response['Content-Length'] = str(end - start + 1)
    else:
        response = FileResponse(handle, content_type=content_type, filename=os.path.basename(path))
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


_RANGE = re.compile(r'bytes=(\d*)-(\d*)')


def _requested_range(request, handle):
    """(start, end) for a single "Range: bytes=..." request, 'unsatisfiable',
    or None for the whole file (no header, or one we don't handle)."""
    match = _RANGE.fullmatch(request.headers.get('Range', '').strip())
    if not match or not (match[1] or match[2]):
        return None
    size = handle.size
    if match[1]:
        start, end = int(match[1]), min(int(match[2]) if match[2] else size - 1, size - 1)
    else:  # "bytes=-500": the last 500 bytes
        start, end = max(size - int(match[2]), 0), size - 1
    return (start, end) if start <= end else 'unsatisfiable'


def _read(handle, length, chunk=64 * 1024):
    try:
        while length > 0:
            data = handle.read(min(chunk, length))
            if not data:
                break
            length -= len(data)
            yield data
    finally:
        handle.close()
