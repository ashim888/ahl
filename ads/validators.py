from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

ad_image_extension_validator = FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])


def validate_ad_image_size(file):
    max_bytes = settings.AD_IMAGE_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'Ad image must be under {settings.AD_IMAGE_MAX_UPLOAD_SIZE_MB} MB.')
