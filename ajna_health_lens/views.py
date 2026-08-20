from django.http import HttpResponse


def robots_txt(request):
    """Plain-text robots.txt — disallows the editorial dashboard and every
    app's /manage/ prefix (none of it is meant to be crawled/indexed), and
    points crawlers at the sitemap. See ajna_health_lens/urls.py.
    """
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /editorial/',
        'Disallow: /manage/',
        '',
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')
