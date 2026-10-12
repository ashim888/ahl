import io
import os

from django import forms
from django.core.files.images import get_image_dimensions
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from PIL import Image, ImageOps

from .models import AdSlot

# An ad is always shown at its zone's size (ads/includes/ad_slot.html), so a
# larger image of the same shape is fine — it just looks sharper on high-
# resolution screens. Kept at most this many times the zone size: sharper
# than that isn't visible, only heavier to download.
MAX_SCALE = 2
# How far the shape may differ (rounding in design tools, e.g. 2185×270).
RATIO_TOLERANCE = 0.01


def fits_zone(width: int, height: int, zone_width: int, zone_height: int) -> bool:
    """At least the zone size, and the same shape."""
    if width < zone_width or height < zone_height:
        return False
    return abs((width / height) / (zone_width / zone_height) - 1) <= RATIO_TOLERANCE


def scaled_to_zone(upload: UploadedFile, zone_width: int, zone_height: int) -> UploadedFile:
    """The upload shrunk to MAX_SCALE × the zone size (or left alone when
    it's already that small or can't be read), same name and format."""
    try:
        upload.seek(0)
        image = ImageOps.exif_transpose(Image.open(upload))
        target = (zone_width * MAX_SCALE, zone_height * MAX_SCALE)
        if image.width <= target[0]:
            return upload
        image_format = image.format or ('PNG' if upload.name.lower().endswith('.png') else 'JPEG')
        image = image.resize(target, Image.LANCZOS)
        out = io.BytesIO()
        if image_format == 'JPEG':
            image.convert('RGB').save(out, 'JPEG', quality=90, optimize=True, progressive=True)
        else:
            image.save(out, image_format, optimize=True)
        return SimpleUploadedFile(os.path.basename(upload.name), out.getvalue(),
                                  content_type=getattr(upload, 'content_type', None))
    except Exception:  # noqa: BLE001 — Pillow raises many types; the original is still a valid ad
        upload.seek(0)
        return upload


class AdSlotForm(forms.ModelForm):
    class Meta:
        model = AdSlot
        fields = ['sponsor_name', 'zone', 'image', 'link_url', 'start_date', 'end_date', 'is_active']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        """Cross-field: an ad image's required size depends on which zone
        it's running in, so this can't live in a per-field validator (those
        only ever see the image, never the zone). Runs whenever both are
        present in the submission — including on an update where only the
        zone changed and the image field was left untouched, since
        `cleaned_data['image']` is still the existing FieldFile in that case
        and `get_image_dimensions` reads it exactly the same way.

        The image must be the zone size or a larger copy of the same shape
        (2× or 3× exports for sharp high-resolution screens); a new upload
        bigger than MAX_SCALE × the zone size is shrunk to that. Smaller
        images (blurry) and other shapes (cropped) are refused. The
        template's CSS sizing (ads/includes/ad_slot.html) is just a second
        line of defense.
        """
        cleaned_data = super().clean()
        zone = cleaned_data.get('zone')
        image = cleaned_data.get('image')
        if zone and image:
            zone_width, zone_height = AdSlot.ZONE_DIMENSIONS[zone]
            width, height = get_image_dimensions(image)
            if not (width and height and fits_zone(width, height, zone_width, zone_height)):
                too_small = bool(width and height and width < zone_width)
                self.add_error('image', (
                    f'"{dict(AdSlot.Zone.choices)[zone]}" needs an image of {zone_width}×{zone_height}px, '
                    f'or a larger copy of the same shape such as {zone_width * 2}×{zone_height * 2}px — '
                    f'the uploaded image is {width}×{height}px'
                    + (', which would look blurry.' if too_small else ', a different shape, so part of it would be cut off.')
                ))
            elif isinstance(image, UploadedFile):
                cleaned_data['image'] = scaled_to_zone(image, zone_width, zone_height)
        return cleaned_data
