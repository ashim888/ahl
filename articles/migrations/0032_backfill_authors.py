"""Moves every byline onto an Author profile (see Author in models.py).

- A byline linked to an account gets that account's Author (one per user),
  created with just name + email — the other profile fields stay blank, so
  the author page keeps falling back to the account's own profile.
- A name-only byline (ArticleAuthor.name, from migration 0030) gets an
  Author per distinct name (case-insensitive), with the first non-blank
  affiliation seen for it.
- Accounts linked to an active editorial-board listing also get an Author,
  since they had a public author page before this change.
"""
from django.db import migrations
from django.utils.text import slugify


def _unique_slug(Author, name, taken):
    base = slugify(name) or 'author'
    if base.isdigit():
        base = f'author-{base}'
    slug, n = base, 2
    while slug in taken or Author.objects.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    taken.add(slug)
    return slug


def forwards(apps, schema_editor):
    Author = apps.get_model('articles', 'Author')
    ArticleAuthor = apps.get_model('articles', 'ArticleAuthor')
    User = apps.get_model('users', 'User')
    taken = set()
    by_user = {}
    by_name = {}

    def author_for_user(user):
        if user.pk not in by_user:
            existing = Author.objects.filter(user=user).first()
            if existing is None:
                name = f'{user.first_name} {user.last_name}'.strip() or user.email
                existing = Author.objects.create(
                    user=user, name=name, email=user.email, slug=_unique_slug(Author, name, taken),
                )
            by_user[user.pk] = existing
        return by_user[user.pk]

    for row in ArticleAuthor.objects.select_related('user').order_by('pk'):
        if row.user_id:
            row.author = author_for_user(row.user)
        else:
            key = ' '.join(row.name.split()).lower()
            author = by_name.get(key)
            if author is None:
                name = ' '.join(row.name.split())
                author = Author.objects.create(
                    name=name, affiliation=row.affiliation, slug=_unique_slug(Author, name, taken),
                )
                by_name[key] = author
            elif row.affiliation and not author.affiliation:
                author.affiliation = row.affiliation
                author.save(update_fields=['affiliation'])
            row.author = author
        row.save(update_fields=['author'])

    for user in User.objects.filter(board_memberships__is_active=True).distinct():
        author_for_user(user)


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0031_author_profiles'),
        ('users', '__first__'),
        ('editorial_board', '0003_editorialboardmember_user'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
