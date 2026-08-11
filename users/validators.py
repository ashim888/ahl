from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

# See ARCHITECTURE.md §7.1 "Author CV" — media/profiles/cvs/, 10 MB, .pdf/.doc/.docx
cv_extension_validator = FileExtensionValidator(allowed_extensions=['pdf', 'doc', 'docx'])

photo_extension_validator = FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])


def validate_cv_file_size(file):
    max_bytes = settings.CV_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'CV file must be under {settings.CV_MAX_UPLOAD_SIZE_MB} MB.')


def validate_photo_size(file):
    max_bytes = settings.PROFILE_PHOTO_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'Photo must be under {settings.PROFILE_PHOTO_MAX_UPLOAD_SIZE_MB} MB.')
