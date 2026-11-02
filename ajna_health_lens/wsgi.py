"""
WSGI config for ajna_health_lens project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from urllib.parse import unquote_to_bytes, urlsplit

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ajna_health_lens.settings')


def decode_path_info(app):
    """The production web server hands PATH_INFO over still percent-encoded
    (/topics/%E0%A4%85.../ reached Django as-is, so every Nepali topic 404'd),
    where WSGI expects it decoded. Decode it here, but only when it matches
    the raw REQUEST_URI — a server that did decode is left alone, so a
    literal %25 isn't decoded twice."""
    def wrapped(environ, start_response):
        path = environ.get('PATH_INFO', '')
        raw = urlsplit(environ.get('REQUEST_URI', '')).path
        if '%' in path and (not raw or raw.endswith(path)):
            environ['PATH_INFO'] = unquote_to_bytes(path).decode('iso-8859-1')
        return app(environ, start_response)
    return wrapped


application = decode_path_info(get_wsgi_application())
