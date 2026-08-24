from django import forms
from django.core.files.images import get_image_dimensions

from .models import AdSlot


class AdSlotForm(forms.ModelForm):
    class Meta:
        model = AdSlot
        fields = ['sponsor_name', 'zone', 'image', 'link_url', 'start_date', 'end_date', 'is_active']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        """Cross-field: an ad image's required pixel dimensions depend on
        which zone it's running in, so this can't live in a per-field
        validator (those only ever see the image, never the zone). Runs
        whenever both are present in the submission — including on an
        update where only the zone changed and the image field was left
        untouched, since `cleaned_data['image']` is still the existing
        FieldFile in that case and `get_image_dimensions` reads it exactly
        the same way. This is the actual fix for oversized/mismatched ad
        renders — the template's CSS sizing (ads/includes/ad_slot.html) is
        just a second line of defense, not the primary one.
        """
        cleaned_data = super().clean()
        zone = cleaned_data.get('zone')
        image = cleaned_data.get('image')
        if zone and image:
            required_width, required_height = AdSlot.ZONE_DIMENSIONS[zone]
            width, height = get_image_dimensions(image)
            if (width, height) != (required_width, required_height):
                self.add_error(
                    'image',
                    f'"{dict(AdSlot.Zone.choices)[zone]}" requires an image exactly '
                    f'{required_width}×{required_height}px — the uploaded image is {width}×{height}px.',
                )
        return cleaned_data
