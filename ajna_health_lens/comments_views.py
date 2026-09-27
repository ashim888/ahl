"""Thin wrappers around django_comments/django_comments_xtd's own views —
same wrapper-view pattern as ckeditor_views.py: rather than fork the
package, override just these URL names (see ajna_health_lens/urls.py —
registered before the django_comments_xtd.urls include so they win the
match) and delegate straight to the real view.

- rate_limited_post_comment: the package's post_comment has no throttle of
  its own — anonymous commenters do get an email-confirmation gate before a
  comment is actually created (COMMENTS_XTD_CONFIRM_EMAIL in settings.py),
  but that doesn't stop a POST flood of confirmation emails.
- rate_limited_post_comment and confirm_comment also give the reader feedback. Out of the box a successful
  post just redirects to `next?c=<id>` with no message at all, landing at
  the top of the article — for an anonymous reader, whose comment isn't
  even saved until they confirm by email, it looked like the comment had
  silently vanished. Instead they redirect to the article's #comments
  section and leave a one-shot "comment flash" in the session, which
  ArticleDetailView pops and article_detail.html shows there.
"""
from urllib.parse import parse_qs, urlsplit

from django.apps import apps
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django_comments.views.comments import post_comment
from django_comments_xtd.models import XtdComment
from django_comments_xtd.views import confirm
from django_ratelimit.decorators import ratelimit

COMMENT_FLASH_SESSION_KEY = 'comment_flash'
COMMENTS_ANCHOR = '#comments'


def _set_comment_flash(request, target_path: str, **flash) -> None:
    """Stores the flash for the article at `target_path` only — see
    pop_comment_flash, which ignores it on any other page.
    """
    request.session[COMMENT_FLASH_SESSION_KEY] = {'path': target_path, **flash}


def pop_comment_flash(request, article_path: str) -> dict | None:
    """Returns (and clears) the pending comment flash if it belongs to the
    article at `article_path`; None otherwise.
    """
    flash = request.session.get(COMMENT_FLASH_SESSION_KEY)
    if not flash or flash.get('path') != article_path:
        return None
    del request.session[COMMENT_FLASH_SESSION_KEY]
    return flash


def _comment_target_path(request) -> str | None:
    """The commented-on object's URL, from the form's own (security-hashed)
    content_type/object_pk fields — not from `next`, which is client-supplied.
    """
    try:
        model = apps.get_model(request.POST['content_type'])
        target = model._default_manager.get(pk=request.POST['object_pk'])
        return target.get_absolute_url()
    except Exception:  # noqa: BLE001 — any lookup failure just means "no feedback redirect"
        return None


def _same_article_next(request, target_path: str) -> str:
    """The form's `next` when it's another address for the *same* article —
    in practice its gift link (/articles/<slug>/gift/<token>/). A reader who
    got in through a gift link and comments must land back on that link;
    the canonical URL would put them in front of the paywall. Anything else
    (another article, another site) falls back to the canonical URL.
    """
    next_url = request.POST.get('next', '')
    if (
        next_url.startswith(target_path)
        and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})
    ):
        return urlsplit(next_url).path
    return target_path


@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def rate_limited_post_comment(request, *args, **kwargs):
    """Posts via the package, then (on success) redirects to the article's
    comments section with a "posted" or "check your email" flash. A 200
    response (validation errors → the package's preview page) passes through.
    """
    response = post_comment(request, *args, **kwargs)
    if response.status_code != 302:
        return response
    target_path = _comment_target_path(request)
    if not target_path:
        return response
    target_path = _same_article_next(request, target_path)

    # The package appends ?c=<pk> for a saved comment, or ?c=<signed key>
    # (not an int) when it only emailed a confirmation link instead.
    comment_ref = parse_qs(urlsplit(response.url).query).get('c', [''])[0]
    if comment_ref.isdigit():
        _set_comment_flash(request, target_path, status='posted', comment_id=int(comment_ref))
    else:
        _set_comment_flash(request, target_path, status='pending', email=request.POST.get('email', ''))
    return redirect(f'{target_path}{COMMENTS_ANCHOR}')


def confirm_comment(request, key):
    """The emailed confirmation link. The package redirects to the new
    comment's permalink with no message; this adds a "now live" flash and
    lands on the article's comments section instead.
    """
    response = confirm(request, key)
    if response.status_code != 302:
        return response
    # The package's redirect goes via its /comments/cr/<ct>/<pk>/#c<id>
    # shortcut, so resolve the article from the comment itself.
    fragment = response.url.partition('#')[2]
    comment_id = fragment[1:] if fragment.startswith('c') else ''
    if not comment_id.isdigit():
        return response
    comment = XtdComment.objects.filter(pk=int(comment_id)).first()
    target = comment.content_object if comment else None
    if target is None or not hasattr(target, 'get_absolute_url'):
        return response
    path = target.get_absolute_url()
    _set_comment_flash(request, path, status='confirmed', comment_id=comment.pk)
    return redirect(f'{path}{COMMENTS_ANCHOR}')
