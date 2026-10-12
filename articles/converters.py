from .models import SHORT_CODE_ALPHABET, SHORT_CODE_LENGTH


class ShortCodeConverter:
    """Matches exactly Article.short_code's shape (5 lowercase-alphanumeric
    chars) — registered ahead of the general `<slug:slug>` article-detail
    pattern in urls.py so a bare code (e.g. /articles/3f2a4/) resolves to
    the short-link redirect instead of falling through to a slug lookup.
    A 5-character slug that isn't anyone's code (e.g. "covid") still works:
    article_short_link falls back to the slug.
    """

    regex = f'[{SHORT_CODE_ALPHABET}]{{{SHORT_CODE_LENGTH}}}'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value
