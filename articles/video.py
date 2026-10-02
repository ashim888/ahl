"""YouTube links for video stories (Article.video_url).

Editors paste whatever link they have — a watch URL, a youtu.be share link,
a Shorts or live link, or an embed URL — and everything else (the embedded
player, the thumbnail for cards and social previews, structured data) is
derived from the 11-character video id, so nothing else needs entering.
The player uses youtube-nocookie.com, so YouTube doesn't set tracking
cookies until the reader actually plays the video.
"""
import re
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ValidationError

_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
_HOSTS = {
    'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
    'youtu.be', 'www.youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com',
}
_PATH_PREFIXES = ('/shorts/', '/live/', '/embed/', '/v/')


def youtube_id(url: str) -> str:
    """The video id in any common YouTube link, or '' if it isn't one."""
    if not url:
        return ''
    parsed = urlparse(url.strip() if '://' in url else f'https://{url.strip()}')
    host = (parsed.hostname or '').lower()
    if host not in _HOSTS:
        return ''
    candidate = ''
    if host.endswith('youtu.be'):
        candidate = parsed.path.lstrip('/').split('/')[0]
    elif parsed.path == '/watch':
        candidate = (parse_qs(parsed.query).get('v') or [''])[0]
    else:
        for prefix in _PATH_PREFIXES:
            if parsed.path.startswith(prefix):
                candidate = parsed.path[len(prefix):].split('/')[0]
                break
    return candidate if _ID.match(candidate) else ''


def start_seconds(url: str) -> int:
    """A start time in the link (?t=90, ?t=1m30s, ?start=90), else 0."""
    query = parse_qs(urlparse(url or '').query)
    raw = (query.get('t') or query.get('start') or [''])[0]
    if raw.isdigit():
        return int(raw)
    match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', raw)
    if not raw or not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def embed_url(url: str) -> str:
    video = youtube_id(url)
    if not video:
        return ''
    start = start_seconds(url)
    return f'https://www.youtube-nocookie.com/embed/{video}?rel=0' + (f'&start={start}' if start else '')


def watch_url(url: str) -> str:
    video = youtube_id(url)
    return f'https://www.youtube.com/watch?v={video}' if video else ''


def thumbnail_url(url: str) -> str:
    """YouTube's own 480x360 thumbnail — always exists for a public video."""
    video = youtube_id(url)
    return f'https://i.ytimg.com/vi/{video}/hqdefault.jpg' if video else ''


def validate_youtube_url(value: str):
    if value and not youtube_id(value):
        raise ValidationError(
            'Paste a YouTube link, e.g. https://www.youtube.com/watch?v=… or https://youtu.be/… '
            '(Shorts and live links work too).',
        )
