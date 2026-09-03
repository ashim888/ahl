"""Rate-limits comment posting. django_comments/django_comments_xtd's own
post_comment view has no throttle of its own — anonymous commenters do get
an email-confirmation gate before a comment is actually created (see
COMMENTS_XTD_CONFIRM_EMAIL in settings.py), but that doesn't stop a POST
flood of confirmation emails/unconfirmed rows. Same wrapper-view pattern as
ckeditor_views.py: rather than fork the package, override just this one URL
name (see ajna_health_lens/urls.py — must be registered before the
django_comments_xtd.urls include so this one wins the match) and delegate
straight to the real view once the throttle passes.
"""
from django_comments.views.comments import post_comment
from django_ratelimit.decorators import ratelimit


@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def rate_limited_post_comment(request, *args, **kwargs):
    return post_comment(request, *args, **kwargs)
