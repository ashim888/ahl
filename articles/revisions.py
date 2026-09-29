"""Revision history for articles: recording snapshots, comparing two of
them, and restoring an old one.

Every explicit save in the editor records an ArticleRevision (who, when,
what they did, and the words as they stood). Background autosaves by the
same person within AUTOSAVE_COALESCE_MINUTES update their latest autosave
entry instead of adding a new one every 20 seconds.
"""
import datetime
import difflib
import html
import re

from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe

from .bylines import summary as byline_summary
from .models import Article, ArticleRevision

AUTOSAVE_COALESCE_MINUTES = 15
SNAPSHOT_FIELDS = ('title', 'abstract', 'html_content', 'references')
FIELD_LABELS = {
    'title': 'Title', 'abstract': 'Summary', 'html_content': 'Article text', 'references': 'References',
    'bylines': 'Authors',
}
# Compared on the History page but never restored: a restore brings back
# the words only, and bylines point at author profiles that may have changed.
COMPARED_FIELDS = SNAPSHOT_FIELDS + ('bylines',)


def _snapshot(article) -> dict:
    return {**{field: getattr(article, field) or '' for field in SNAPSHOT_FIELDS}, 'bylines': byline_summary(article)}


def record_revision(article, user, action) -> ArticleRevision:
    """Snapshot `article` as it is now. Autosaves coalesce (see module doc)."""
    now = timezone.now()
    if action == ArticleRevision.Action.AUTOSAVED:
        latest = article.revisions.first()
        if (
            latest and latest.action == ArticleRevision.Action.AUTOSAVED and latest.user_id == getattr(user, 'pk', None)
            and now - latest.created_at < datetime.timedelta(minutes=AUTOSAVE_COALESCE_MINUTES)
        ):
            for field, value in _snapshot(article).items():
                setattr(latest, field, value)
            latest.status = article.status
            latest.created_at = now
            latest.save()
            return latest
    return ArticleRevision.objects.create(
        article=article, user=user, action=action, status=article.status, created_at=now, **_snapshot(article),
    )


def restore_revision(revision, user) -> Article:
    """Copies an old version's words back into the article (status and
    everything else unchanged) and records that as a new revision — so a
    restore can itself be undone from the history."""
    article = revision.article
    for field in SNAPSHOT_FIELDS:
        setattr(article, field, getattr(revision, field) or ('' if field != 'html_content' else None))
    if article.status == Article.Status.PUBLISHED:
        article.last_updated_at = timezone.now()
    article.save()
    record_revision(article, user, ArticleRevision.Action.RESTORED)
    return article


def _plain_words(value: str) -> list[str]:
    """Visible text of a field as words (tags stripped, block breaks kept as
    paragraph markers) — what a reader would notice changing."""
    text = re.sub(r'</(p|h[1-6]|li|blockquote|tr)>|<br\s*/?>', '\n\n', value or '', flags=re.I)
    text = html.unescape(strip_tags(text))
    words = []
    for paragraph in re.split(r'\n\s*\n', text):
        paragraph = ' '.join(paragraph.split())
        if paragraph:
            words.extend(paragraph.split(' '))
            words.append('\n')
    if words and words[-1] == '\n':
        words.pop()
    return words


def plain_text(value: str) -> str:
    """A field's visible words as escaped HTML with paragraph breaks — how
    the very first recorded version is shown (nothing to compare it to)."""
    words = _plain_words(value)
    return mark_safe(' '.join(html.escape(w) for w in words).replace(' \n ', '<br><br>'))


def word_diff(old: str, new: str) -> str:
    """HTML with <del>/<ins> marking removed/added words. Escaped — safe to
    render as-is."""
    before, after = _plain_words(old), _plain_words(new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if op == 'equal':
            out.append(' '.join(html.escape(w) for w in before[i1:i2]))
        if op in ('delete', 'replace'):
            out.append('<del>' + ' '.join(html.escape(w) for w in before[i1:i2]) + '</del>')
        if op in ('insert', 'replace'):
            out.append('<ins>' + ' '.join(html.escape(w) for w in after[j1:j2]) + '</ins>')
    return mark_safe(' '.join(out).replace(' \n ', '<br><br>').replace('\n', '<br><br>'))


def compare(old, new) -> list[dict]:
    """Per-field differences between two revisions (unchanged fields
    omitted). `old` may be None for the first revision."""
    changes = []
    for field in COMPARED_FIELDS:
        if field == 'bylines' and (new.bylines is None or (old is not None and old.bylines is None)):
            continue  # not recorded on one side (an older revision)
        after = getattr(new, field, '') or ''
        if old is None:
            if after:
                changes.append({'field': field, 'label': FIELD_LABELS[field], 'diff': plain_text(after)})
            continue
        before = getattr(old, field, '') or ''
        if before != after:
            changes.append({'field': field, 'label': FIELD_LABELS[field], 'diff': word_diff(before, after)})
    return changes
