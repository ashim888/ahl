"""Who is visiting: their real IP address, and whether they are a crawler."""
import re

# Search engines, link previews and monitors name themselves in the User-Agent.
CRAWLER_RE = re.compile(r'bot|crawl|spider|slurp|facebookexternalhit|preview|monitor|curl|wget|python-requests', re.I)


def client_ip(request) -> str:
    """The visitor's IP address. Behind nginx every request arrives from
    127.0.0.1, so nginx passes the real one as X-Real-IP, set from
    $remote_addr (ARCHITECTURE.md §9). A visitor can't fake it, since nginx
    overwrites the header. Without nginx (runserver, tests) it is REMOTE_ADDR.
    Used for every `ratelimit(key='ip')` (settings.RATELIMIT_IP_META_KEY)."""
    return request.META.get('HTTP_X_REAL_IP') or request.META['REMOTE_ADDR']


def is_crawler(request) -> bool:
    """True for a self-declared bot, so it isn't counted as a reader (article
    views, ad impressions and clicks). Bots that pretend to be browsers still count."""
    return bool(CRAWLER_RE.search(request.META.get('HTTP_USER_AGENT', '')))
