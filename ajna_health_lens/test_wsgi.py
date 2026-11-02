"""ajna_health_lens/wsgi.py: decode_path_info."""
from django.test import SimpleTestCase

from .wsgi import decode_path_info


def _seen_path(path_info, request_uri=None):
    seen = {}
    app = decode_path_info(lambda environ, start_response: seen.setdefault('path', environ['PATH_INFO']))
    environ = {'PATH_INFO': path_info}
    if request_uri is not None:
        environ['REQUEST_URI'] = request_uri
    app(environ, None)
    return seen['path']


class DecodePathInfoTests(SimpleTestCase):
    """Nepali topic URLs 404'd in production: the server left PATH_INFO percent-encoded."""

    def test_encoded_path_is_decoded_the_wsgi_way(self):
        path = _seen_path('/topics/%E0%A4%85/', '/topics/%E0%A4%85/?page=2')
        # WSGI carries the UTF-8 bytes as latin-1; Django turns them back into 'अ'.
        self.assertEqual(path.encode('iso-8859-1').decode('utf-8'), '/topics/अ/')

    def test_already_decoded_path_is_left_alone(self):
        # The server decoded %2541 to %41; decoding again would give 'A'.
        self.assertEqual(_seen_path('/topics/%41/', '/topics/%2541/'), '/topics/%41/')
        self.assertEqual(_seen_path('/topics/actfast/', '/topics/actfast/'), '/topics/actfast/')
