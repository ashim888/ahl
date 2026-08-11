from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

# See ARCHITECTURE.md §7.1 "Issue Cover"
cover_image_extension_validator = FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])


def validate_cover_image_size(file):
    max_bytes = settings.ISSUE_COVER_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'Cover image must be under {settings.ISSUE_COVER_MAX_UPLOAD_SIZE_MB} MB.')
