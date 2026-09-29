"""Bylines edited inside the article form (the "Authors" box in its sidebar).

The box keeps its state as JSON in a hidden `bylines` input, one entry per
author in byline order:

    {"id": 12, "corresponding": true}                       an existing Author
    {"key": "n1", "name": "Sita Rai", "affiliation": "...",  a new Author, created
     "email": "...", "corresponding": false}                 when the article saves

New authors are created only when the article is actually saved (explicit
save or autosave), never while typing, so an abandoned draft leaves no stray
author profiles behind. Only name, affiliation and email are asked for here;
the rest of the profile is filled in later at /manage/authors/.
"""
import json

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Case, IntegerField, Q, When

from .models import ArticleAuthor, Author

MAX_BYLINES = 20
SEARCH_LIMIT = 8


def author_payload(author: Author) -> dict:
    """What the Authors box shows for one existing author."""
    return {
        'id': author.pk, 'name': author.name, 'affiliation': author.display_affiliation,
        'has_account': bool(author.user_id),
    }


def initial_json(article) -> str:
    """The article's current bylines, in the hidden input's JSON shape."""
    if not article.pk:
        return '[]'
    return json.dumps([
        {**author_payload(byline.author), 'corresponding': byline.is_corresponding}
        for byline in article.articleauthor_set.select_related('author__user').order_by('order')
    ])


def search(query: str) -> list[dict]:
    """Active authors whose name (or affiliation) matches, names starting
    with the query first."""
    query = (query or '').strip()
    if not query:
        return []
    authors = (
        Author.objects.filter(is_active=True)
        .filter(Q(name__icontains=query) | Q(affiliation__icontains=query))
        .annotate(rank=Case(When(name__istartswith=query, then=0), default=1, output_field=IntegerField()))
        .select_related('user')
        .order_by('rank', 'name')[:SEARCH_LIMIT]
    )
    return [author_payload(author) for author in authors]


def parse(raw: str, article) -> list[dict]:
    """Validates the submitted JSON into entries of {'author': Author or
    None, 'name', 'affiliation', 'email', 'key', 'corresponding'}. Raises
    ValidationError with an editor-facing message."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        raise ValidationError('The author list could not be read — reload the page and try again.')
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValidationError('The author list could not be read — reload the page and try again.')
    if len(items) > MAX_BYLINES:
        raise ValidationError(f'An article can credit at most {MAX_BYLINES} authors.')

    ids = []
    for item in items:
        if item.get('id') is not None:
            try:
                ids.append(int(item['id']))
            except (TypeError, ValueError):
                raise ValidationError('The author list could not be read — reload the page and try again.')
    # Inactive authors can't be newly added, but one already credited on
    # this article stays (deactivating an author never rewrites old bylines).
    current = set(article.articleauthor_set.values_list('author_id', flat=True)) if article.pk else set()
    found = {
        author.pk: author
        for author in Author.objects.filter(pk__in=ids).filter(Q(is_active=True) | Q(pk__in=current))
    }

    entries, seen_ids, seen_new = [], set(), set()
    for item in items:
        corresponding = bool(item.get('corresponding'))
        if item.get('id') is not None:
            author = found.get(int(item['id']))
            if author is None:
                raise ValidationError('One of the authors you picked is no longer available — remove it and pick again.')
            if author.pk in seen_ids:
                continue
            seen_ids.add(author.pk)
            entries.append({'author': author, 'corresponding': corresponding, 'key': ''})
            continue

        name = ' '.join(str(item.get('name') or '').split())
        affiliation = ' '.join(str(item.get('affiliation') or '').split())
        email = str(item.get('email') or '').strip()
        if not name:
            raise ValidationError('Each new author needs a name.')
        if len(name) > 255 or len(affiliation) > 255:
            raise ValidationError(f'"{name[:40]}": name and affiliation must be under 255 characters.')
        if email:
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError(f'"{name}": "{email}" is not a valid email address.')
        if name.lower() in seen_new:
            continue
        seen_new.add(name.lower())
        entries.append({
            'author': None, 'name': name, 'affiliation': affiliation, 'email': email,
            'key': str(item.get('key') or '')[:40], 'corresponding': corresponding,
        })
    return entries


def _author_for_new_entry(entry: dict) -> Author:
    """Reuses an existing active author with exactly this name (ignoring
    case) — unless both have emails and they differ, i.e. clearly two
    different people — otherwise creates one."""
    for existing in Author.objects.filter(name__iexact=entry['name'], is_active=True):
        if not (entry['email'] and existing.email and existing.email.lower() != entry['email'].lower()):
            return existing
    return Author.objects.create(name=entry['name'], affiliation=entry['affiliation'], email=entry['email'])


@transaction.atomic
def save(article, entries: list[dict]) -> dict[str, int]:
    """Makes the article's bylines exactly `entries`, in order. Returns
    {client key: author id} for new entries, so the page can swap them for
    the saved author (and a second autosave doesn't create them again)."""
    created, keep = {}, []
    for order, entry in enumerate(entries):
        author = entry['author']
        if author is None:
            author = _author_for_new_entry(entry)
            if entry['key']:
                created[entry['key']] = author.pk
        if author.pk in keep:
            continue
        keep.append(author.pk)
        ArticleAuthor.objects.update_or_create(
            article=article, author=author, defaults={'order': order, 'is_corresponding': entry['corresponding']},
        )
    article.articleauthor_set.exclude(author_id__in=keep).delete()
    return created


def summary(article) -> str:
    """Bylines as one line of text, for revision history."""
    return ', '.join(
        f'{byline.author.name}{" (corresponding)" if byline.is_corresponding else ""}'
        for byline in article.articleauthor_set.select_related('author').order_by('order')
    )


def preview_bylines(entries: list[dict]) -> list[ArticleAuthor]:
    """Unsaved ArticleAuthor rows for the preview page — nothing is created."""
    rows = []
    for order, entry in enumerate(entries):
        author = entry['author'] or Author(name=entry['name'], affiliation=entry['affiliation'])
        rows.append(ArticleAuthor(author=author, order=order, is_corresponding=entry['corresponding']))
    return rows
