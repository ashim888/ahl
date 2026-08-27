from django.http import HttpResponse


def robots_txt(request):
    """Plain-text robots.txt — disallows the editorial dashboard and every
    app's /manage/ prefix (none of it is meant to be crawled/indexed), and
    points crawlers at both sitemaps. See ajna_health_lens/urls.py.
    Referencing the Google News sitemap here isn't required (Google News
    sitemaps are normally submitted directly via Search Console), but it's
    harmless and keeps every sitemap discoverable from one place.
    """
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /editorial/',
        'Disallow: /manage/',
        '',
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
        f'Sitemap: {request.build_absolute_uri("/news-sitemap.xml")}',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')
