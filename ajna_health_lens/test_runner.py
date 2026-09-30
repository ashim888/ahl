"""Test runner that keeps uploads out of the real media folders.

Tests that save files (ads, featured images, PDFs, CVs, editor images)
used to write into the project's own media/ — thousands of leftover
files, all publicly served. Every test run now gets throwaway MEDIA_ROOT,
PRIVATE_MEDIA_ROOT and ORPHAN_MEDIA_ROOT folders, removed afterwards.
"""
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner


class IsolatedMediaTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media_tmp = Path(tempfile.mkdtemp(prefix='ahl-test-media-'))
        self._saved_media = {}
        for name in ('MEDIA_ROOT', 'PRIVATE_MEDIA_ROOT', 'ORPHAN_MEDIA_ROOT'):
            self._saved_media[name] = getattr(settings, name)
            setattr(settings, name, self._media_tmp / name.lower())

    def teardown_test_environment(self, **kwargs):
        for name, value in self._saved_media.items():
            setattr(settings, name, value)
        shutil.rmtree(self._media_tmp, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
