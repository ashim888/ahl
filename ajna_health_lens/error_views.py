"""Error pages that need the full site around them (handler404, the CSRF
failure view). The 500 page is a plain template (templates/500.html) on
purpose — it must render even when the database is down."""
import json
import logging
import re

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

logger = logging.getLogger(__name__)


def page_not_found(request, exception=None):
    """404 with a search box pre-filled from the missing address —
    /articles/malaria-vaccine-trial/ suggests "malaria vaccine trial"."""
    last_part = next((part for part in reversed(request.path.split('/')) if part), '')
    words = re.sub(r'[-_]+', ' ', re.sub(r'\.\w+$', '', last_part)).strip()
    return render(request, '404.html', {'suggested_query': words[:80]}, status=404)


def csrf_failure(request, reason=''):
    """A form sent with a missing or stale security token — usually a page
    left open too long. Explain it instead of a bare 403."""
    return render(request, '403_csrf.html', status=403)


@csrf_exempt
@require_POST
@ratelimit(key='ip', rate='60/h', block=True)
def csp_report(request):
    """Browsers POST Content-Security-Policy violations here. Logged (and so
    visible in error tracking), never emailed — one bad browser extension
    could otherwise flood the inbox."""
    try:
        report = json.loads(request.body or b'{}').get('csp-report', {})
    except ValueError:
        report = {}
    logger.warning(
        'CSP violation: %s blocked %s on %s', report.get('violated-directive') or report.get('effective-directive'),
        report.get('blocked-uri'), report.get('document-uri'),
    )
    return HttpResponse(status=204)
