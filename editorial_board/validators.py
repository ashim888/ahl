from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

# See ARCHITECTURE.md §7.1 "Profile Photo"
photo_extension_validator = FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])


def validate_photo_size(file):
    max_bytes = settings.PROFILE_PHOTO_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'Photo must be under {settings.PROFILE_PHOTO_MAX_UPLOAD_SIZE_MB} MB.')
