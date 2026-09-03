"""Shared file-content validators. FileExtensionValidator (used throughout
users/articles/submissions/editorial_board/issues/ads validators.py) only
ever looks at the filename — a file renamed from `payload.html` to
`resume.pdf` sails through it untouched. This adds a lightweight magic-byte
check for the document types this project actually accepts uploads of
(PDF/DOC/DOCX). Deliberately not python-magic/libmagic — that's a native
system dependency, and this project has already hit real install friction
with one native dependency (mysqlclient, see ROADMAP.md Risk Register);
these three signatures cover the actual accepted extensions without adding
another. Image uploads don't need an equivalent here — Django's ImageField
already opens every upload with Pillow and rejects anything that isn't a
real, decodable image, which is a stronger check than a magic-byte read.
"""
from django.core.exceptions import ValidationError

_PDF_MAGIC = b'%PDF-'
_DOCX_MAGIC = b'PK\x03\x04'  # .docx is a zip archive
_DOC_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'  # legacy OLE compound file


def validate_document_content(file):
    """Call alongside a FileExtensionValidator(allowed_extensions=[...]),
    not instead of it — this only checks that the file's own bytes match
    the extension it claims, not what extensions are allowed at all.
    """
    name = file.name.lower()
    file.seek(0)
    header = file.read(8)
    file.seek(0)
    if name.endswith('.pdf'):
        if not header.startswith(_PDF_MAGIC):
            raise ValidationError("This file doesn't look like a real PDF — its content doesn't match a .pdf file.")
    elif name.endswith('.docx'):
        if not header.startswith(_DOCX_MAGIC):
            raise ValidationError("This file doesn't look like a real Word document — its content doesn't match a .docx file.")
    elif name.endswith('.doc'):
        if header != _DOC_MAGIC:
            raise ValidationError("This file doesn't look like a real Word document — its content doesn't match a .doc file.")
