"""The automatic share picture: Facebook, WhatsApp, X and LinkedIn show a
link's og:image at about 1.91:1 and crop anything else from the middle, so a
poster or diagram loses its top and bottom. This makes a 1200×630 card from
the featured image instead, framed the way the site frames it:

- a picture shown whole on the site (square/tall, very wide, or "whole"
  chosen in the editor) sits whole on a blurred, dimmed copy of itself;
- any other picture is cropped around the editor's focal point.

Cards are made on first use (the article page asks for one) and kept in
storage under a name that changes whenever the picture, fit or focal point
does, so an edit gets a fresh card and a share preview never shows a stale
one. An uploaded "Share image" on the article always wins over this.
"""
import hashlib
import io
import logging

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 1200, 630
QUALITY = 85
# Bump to rebuild every card after changing how they look.
VERSION = 1


def card_name(article) -> str:
    """Storage path of this article's card for its current picture/framing."""
    key = (f'{VERSION}|{article.featured_image.name}|{article.featured_image_fit}|'
           f'{article.featured_image_focus_x}|{article.featured_image_focus_y}|{article.hero_shows_whole}')
    digest = hashlib.sha1(key.encode()).hexdigest()[:12]
    return f'articles/share/{article.pk}-{digest}.jpg'


def _crop_around(image: Image.Image, focus_x: float, focus_y: float) -> Image.Image:
    """The largest 1.91:1 window of `image` centred as near the focal
    point as the edges allow, scaled to the card size."""
    width, height = image.size
    target = WIDTH / HEIGHT
    if width / height > target:
        crop_w, crop_h = round(height * target), height
    else:
        crop_w, crop_h = width, round(width / target)
    left = min(max(round(width * focus_x / 100 - crop_w / 2), 0), width - crop_w)
    top = min(max(round(height * focus_y / 100 - crop_h / 2), 0), height - crop_h)
    return image.crop((left, top, left + crop_w, top + crop_h)).resize((WIDTH, HEIGHT), Image.LANCZOS)


def _whole_on_backdrop(image: Image.Image) -> Image.Image:
    """The whole picture, centred, on a blurred and darkened fill of itself."""
    backdrop = _crop_around(image, 50, 50).filter(ImageFilter.GaussianBlur(28))
    backdrop = Image.blend(backdrop, Image.new('RGB', backdrop.size, (17, 17, 17)), 0.45)
    inner = image.copy()
    inner.thumbnail((WIDTH - 80, HEIGHT - 60), Image.LANCZOS)
    backdrop.paste(inner, ((WIDTH - inner.width) // 2, (HEIGHT - inner.height) // 2))
    return backdrop


def render(data: bytes, *, whole: bool, focus_x: float = 50, focus_y: float = 50) -> bytes:
    """A 1200×630 JPEG of the picture in `data`."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if image.mode in ('RGBA', 'LA', 'P'):
        # Transparent PNGs (logos, charts) go on white, not black.
        image = image.convert('RGBA')
        flat = Image.new('RGB', image.size, (255, 255, 255))
        flat.paste(image, mask=image.getchannel('A'))
        image = flat
    else:
        image = image.convert('RGB')
    card = _whole_on_backdrop(image) if whole else _crop_around(image, focus_x, focus_y)
    out = io.BytesIO()
    card.save(out, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def share_card_url(article) -> str:
    """URL of the article's automatic share card, made now if it doesn't
    exist yet — or '' when there's no featured image or it can't be read
    (the caller then falls back to the plain featured image)."""
    if not article.featured_image or not article.pk:
        return ''
    name = card_name(article)
    try:
        if not default_storage.exists(name):
            if not article.featured_image.storage.exists(article.featured_image.name):
                return ''  # the picture's file is gone — nothing to make a card from
            with article.featured_image.open('rb') as source:
                data = render(source.read(), whole=article.hero_shows_whole,
                              focus_x=article.featured_image_focus_x, focus_y=article.featured_image_focus_y)
            # save() may pick another name if two requests race — use what it returns.
            name = default_storage.save(name, ContentFile(data))
        return default_storage.url(name)
    except Exception:  # noqa: BLE001 — a missing/broken file must never break the article page
        logger.warning('Could not make the share card for article %s', article.pk, exc_info=True)
        return ''
