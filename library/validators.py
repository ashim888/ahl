from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

# Documents, slides and data people actually share in Nepal's health sector.
# No archives or executables: zip files can't be checked and could hide anything.
LIBRARY_EXTENSIONS = ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'csv']
library_file_extension_validator = FileExtensionValidator(allowed_extensions=LIBRARY_EXTENSIONS)


def validate_library_file_size(file):
    max_bytes = settings.LIBRARY_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'The file must be under {settings.LIBRARY_MAX_UPLOAD_SIZE_MB} MB.')
