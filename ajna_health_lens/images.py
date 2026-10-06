"""Uploaded images are made web-sized before they're stored.

Every ImageField upload (featured/social images, photos, covers, ads) goes
through the pre_save receiver below, and every image inserted into article
text through InlineImageStorage (ckeditor_views.py). Each image is:

- turned upright (phone photos are often stored sideways with an EXIF flag);
- stripped of metadata — EXIF can carry the GPS location and camera owner;
- shrunk so its longest side is at most IMAGE_MAX_DIMENSION px (ads keep
  their exact size — each ad zone needs exact pixel dimensions);
- re-encoded (JPEG quality IMAGE_JPEG_QUALITY, progressive; optimized PNG;
  WebP at the same quality) — kept only when that's actually smaller or the
  image was resized, so a well-compressed upload is never made worse.

The format and file extension never change. Animated GIFs and anything
Pillow can't read are stored untouched. `manage.py compress_images` applies
the same to images uploaded before this existed.
"""
import io
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import ImageField
from django.db.models.signals import pre_save
from django.dispatch import receiver
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Models whose images must keep their exact pixel size.
KEEP_SIZE_MODELS = {'ads.adslot'}


def optimize_bytes(data: bytes, *, keep_size: bool = False) -> bytes | None:
    """Web-sized bytes for an image, or None to keep the original as it is.
    Never raises: a file Pillow can't handle is simply stored untouched."""
    try:
        return _optimize(data, keep_size)
    except Exception:  # noqa: BLE001 — Pillow raises many types (SyntaxError for broken PNGs…)
        logger.warning('Image left as uploaded (could not optimize it)', exc_info=True)
        return None


def _optimize(data: bytes, keep_size: bool) -> bytes | None:
    image = Image.open(io.BytesIO(data))
    image_format = image.format
    if image_format not in ('JPEG', 'PNG', 'WEBP') or getattr(image, 'is_animated', False):
        return None
    image.load()
    has_metadata = bool(image.info.get('exif')) or bool(image.getexif())
    image = ImageOps.exif_transpose(image)
    resized = False
    limit = settings.IMAGE_MAX_DIMENSION
    if not keep_size and max(image.size) > limit:
        image.thumbnail((limit, limit), Image.LANCZOS)
        resized = True

    out = io.BytesIO()
    quality = settings.IMAGE_JPEG_QUALITY
    if image_format == 'JPEG':
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        image.save(out, 'JPEG', quality=quality, optimize=True, progressive=True)
    elif image_format == 'PNG':
        image.save(out, 'PNG', optimize=True)
    else:
        image.save(out, 'WEBP', quality=quality, method=6)
    result = out.getvalue()
    if resized or has_metadata or len(result) < len(data):
        return result
    return None


def optimize_file(content, *, keep_size: bool = False):
    """An uploaded file → a ContentFile with the optimized image (same
    name), or the original object when there's nothing to gain."""
    try:
        content.seek(0)
        data = content.read()
        content.seek(0)
    except (OSError, ValueError, AttributeError):
        return content
    optimized = optimize_bytes(data, keep_size=keep_size)
    if optimized is None:
        return content
    logger.info('Optimized image %s: %d → %d bytes', getattr(content, 'name', ''), len(data), len(optimized))
    return ContentFile(optimized, name=getattr(content, 'name', None))


@receiver(pre_save, dispatch_uid='optimize_uploaded_images')
def optimize_uploaded_images(sender, instance, raw=False, **kwargs):
    """Before any model is saved: optimize each newly uploaded image."""
    if raw or not settings.IMAGE_OPTIMIZE_UPLOADS:
        return
    keep_size = sender._meta.label_lower in KEEP_SIZE_MODELS
    for field in sender._meta.concrete_fields:
        if not isinstance(field, ImageField):
            continue
        value = getattr(instance, field.attname)
        if not value or getattr(value, '_committed', True):
            continue  # nothing new uploaded
        optimized = optimize_file(value.file, keep_size=keep_size)
        if optimized is not value.file:
            value.file = optimized
