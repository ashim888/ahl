from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from ajna_health_lens.validators import validate_document_content

# See ARCHITECTURE.md §7.1 "Manuscript PDF/Word" — 50 MB, .pdf/.doc/.docx
manuscript_extension_validator = FileExtensionValidator(allowed_extensions=['pdf', 'doc', 'docx'])


def validate_manuscript_file_size(file):
    max_bytes = settings.MANUSCRIPT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'Manuscript file must be under {settings.MANUSCRIPT_MAX_UPLOAD_SIZE_MB} MB.')


def infer_manuscript_file_type(filename):
    return 'pdf' if filename.lower().endswith('.pdf') else 'word'
