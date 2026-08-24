import secrets
import string

from django.db import migrations

SHORT_CODE_ALPHABET = string.ascii_lowercase + string.digits
SHORT_CODE_LENGTH = 5


def generate_short_code():
    return ''.join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


def backfill_short_codes(apps, schema_editor):
    Article = apps.get_model('articles', 'Article')
    existing = set(Article.objects.exclude(short_code='').values_list('short_code', flat=True))
    for article in Article.objects.filter(short_code=''):
        code = generate_short_code()
        while code in existing:
            code = generate_short_code()
        existing.add(code)
        article.short_code = code
        article.save(update_fields=['short_code'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0016_article_short_code'),
    ]

    operations = [
        migrations.RunPython(backfill_short_codes, noop_reverse),
    ]
