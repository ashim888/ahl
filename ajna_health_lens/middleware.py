from django.middleware.common import BrokenLinkEmailsMiddleware


class InternalBrokenLinkEmailsMiddleware(BrokenLinkEmailsMiddleware):
    """Django's broken-link email, limited to links on our own pages — the
    ones we can fix. Dead links on other websites (and bots) aren't emailed."""

    def is_ignorable_request(self, request, uri, domain, referer):
        if not self.is_internal_request(domain, referer):
            return True
        return super().is_ignorable_request(request, uri, domain, referer)


def ignore_browser_language(get_response):
    """Nepali first: LocaleMiddleware (next in MIDDLEWARE) would otherwise pick
    English for any browser that asks for it, and most phones in Nepal ask for
    en-US. Without the header it uses the switcher's cookie, else LANGUAGE_CODE."""
    def middleware(request):
        request.META.pop('HTTP_ACCEPT_LANGUAGE', None)
        return get_response(request)
    return middleware


class SecurityHeadersMiddleware:
    """Adds Content-Security-Policy (or -Report-Only) and Permissions-Policy
    to every response, from settings.CSP_DIRECTIVES / PERMISSIONS_POLICY.
    Violations are POSTed by browsers to /csp-report/ (csp_report below)."""

    def __init__(self, get_response):
        from django.conf import settings

        self.get_response = get_response
        directives = dict(settings.CSP_DIRECTIVES)
        if not settings.DEBUG:
            directives['upgrade-insecure-requests'] = []
        directives['report-uri'] = ['/csp-report/']
        self.policy = '; '.join(' '.join([name, *values]) for name, values in directives.items())
        self.header = 'Content-Security-Policy-Report-Only' if settings.CSP_REPORT_ONLY else 'Content-Security-Policy'
        self.permissions = settings.PERMISSIONS_POLICY

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(self.header, self.policy)
        if self.permissions:
            response.setdefault('Permissions-Policy', self.permissions)
        return response
