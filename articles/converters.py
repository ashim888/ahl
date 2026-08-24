from .models import SHORT_CODE_ALPHABET, SHORT_CODE_LENGTH


class ShortCodeConverter:
    """Matches exactly Article.short_code's shape (5 lowercase-alphanumeric
    chars) — registered ahead of the general `<slug:slug>` article-detail
    pattern in urls.py so a bare code (e.g. /articles/3f2a4/) resolves to
    the short-link redirect instead of falling through to a slug lookup
    that would 404 (a real slug is the full "title-slug-code" string, not
    just the code on its own).
    """

    regex = f'[{SHORT_CODE_ALPHABET}]{{{SHORT_CODE_LENGTH}}}'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value
