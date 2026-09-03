from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from ajna_health_lens.validators import validate_document_content

# See ARCHITECTURE.md §7.1 "Article PDF" / featured image
article_pdf_extension_validator = FileExtensionValidator(allowed_extensions=['pdf'])
article_image_extension_validator = FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])


def validate_article_pdf_size(file):
    max_bytes = settings.ARTICLE_PDF_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'Article PDF must be under {settings.ARTICLE_PDF_MAX_UPLOAD_SIZE_MB} MB.')


def validate_featured_image_size(file):
    max_bytes = settings.ARTICLE_IMAGE_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(f'Featured image must be under {settings.ARTICLE_IMAGE_MAX_UPLOAD_SIZE_MB} MB.')
