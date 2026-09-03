from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .validators import validate_document_content


class DocumentContentValidatorTests(TestCase):
    """FileExtensionValidator only ever looks at the filename — these check
    the magic-byte companion check added alongside it (see
    ajna_health_lens/validators.py) actually catches a disguised upload,
    not just a genuine one with the wrong name.
    """

    def test_real_pdf_passes(self):
        file = SimpleUploadedFile('resume.pdf', b'%PDF-1.4 real pdf bytes', content_type='application/pdf')
        validate_document_content(file)  # should not raise

    def test_html_disguised_as_pdf_is_rejected(self):
        file = SimpleUploadedFile('resume.pdf', b'<html><script>alert(1)</script></html>', content_type='application/pdf')
        with self.assertRaises(ValidationError):
            validate_document_content(file)

    def test_real_docx_passes(self):
        file = SimpleUploadedFile('cv.docx', b'PK\x03\x04 real zip/docx bytes', content_type='application/vnd.openxmlformats')
        validate_document_content(file)  # should not raise

    def test_non_zip_disguised_as_docx_is_rejected(self):
        file = SimpleUploadedFile('cv.docx', b'not a zip at all', content_type='application/vnd.openxmlformats')
        with self.assertRaises(ValidationError):
            validate_document_content(file)

    def test_real_doc_passes(self):
        file = SimpleUploadedFile('cv.doc', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest of ole file', content_type='application/msword')
        validate_document_content(file)  # should not raise

    def test_fake_doc_is_rejected(self):
        file = SimpleUploadedFile('cv.doc', b'just some text', content_type='application/msword')
        with self.assertRaises(ValidationError):
            validate_document_content(file)

    def test_validator_does_not_consume_the_file_pointer(self):
        # A validator that leaves the pointer mid-file would corrupt the
        # actual upload once Django goes on to save it.
        file = SimpleUploadedFile('resume.pdf', b'%PDF-1.4 real pdf bytes', content_type='application/pdf')
        validate_document_content(file)
        self.assertEqual(file.read(), b'%PDF-1.4 real pdf bytes')
