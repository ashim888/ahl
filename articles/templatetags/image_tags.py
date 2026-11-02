"""Smaller copies of uploaded pictures, so a phone isn't sent a 1.5 MB
original for a 400px card. Copies are WebP, made with Pillow the first time
a page asks for them, saved under MEDIA_ROOT/resized/ and reused after that.

    <img src="{{ url }}" srcset="{{ url|srcset }}" sizes="…">
    <img src="{{ url|backdrop|default:url }}">   (a pre-blurred colour wash)

Anything that isn't an upload (a YouTube thumbnail, '') passes through
untouched: srcset gives '', backdrop gives ''.
"""
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import unquote

from django import template
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageFilter, ImageOps

register = template.Library()

WIDTHS = (480, 960, 1600)
BACKDROP_WIDTH = 64


def _upload_name(url) -> str | None:
    """Storage name of an uploaded file from its URL, or None if `url` isn't one."""
    url = str(url or '')
    # unquote: storage percent-encodes non-ASCII names (Devanagari filenames) in URLs.
    return unquote(url[len(settings.MEDIA_URL):]) if url.startswith(settings.MEDIA_URL) else None


def _variant(name: str, width: int, blur: int = 0) -> str:
    """Storage name of `name` scaled to `width` (and blurred), made if missing.
    Raises OSError if the original can't be read."""
    tag = f'{width}w-blur' if blur else f'{width}w'
    out = f'resized/{PurePosixPath(name).with_suffix("")}-{tag}.webp'
    if default_storage.exists(out):
        return out
    with default_storage.open(name) as f, Image.open(f) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((width, width * 10))
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA')
        if blur:
            img = img.convert('RGB').filter(ImageFilter.GaussianBlur(blur))
        buf = BytesIO()
        img.save(buf, 'WEBP', quality=80)
    return default_storage.save(out, ContentFile(buf.getvalue()))


def _cached(key: str, build):
    """`build()` once per upload. shortcut: the result is cached forever, so
    deleting files under resized/ needs a cache clear too."""
    value = cache.get(key)
    if value is None:
        try:
            value = build()
        except Exception:  # Pillow signals some broken files with SyntaxError; a damaged upload must not break the page.
            value = ''
        cache.set(key, value, None)
    return value


@register.filter
def srcset(url) -> str:
    """WebP copies at each of WIDTHS narrower than the original, then the
    original at its own width."""
    name = _upload_name(url)
    if not name:
        return ''

    def build():
        with default_storage.open(name) as f, Image.open(f) as img:
            original = ImageOps.exif_transpose(img).width
        parts = [f'{default_storage.url(_variant(name, w))} {w}w' for w in WIDTHS if w < original]
        return ', '.join(parts + [f'{url} {original}w']) if parts else ''

    return _cached(f'srcset:{name}', build)


@register.filter
def backdrop(url) -> str:
    """A 64px, pre-blurred copy for a full-bleed colour wash: the browser
    stretches it smooth for free, instead of running a CSS blur over a
    full-size picture."""
    name = _upload_name(url)
    if not name:
        return ''
    return _cached(f'backdrop:{name}', lambda: default_storage.url(_variant(name, BACKDROP_WIDTH, blur=2)))
