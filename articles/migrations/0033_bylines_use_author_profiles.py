"""Finishes the switch to Author profiles: every ArticleAuthor row has an
author after 0032, so the column becomes required and the old per-row
account/name fields (and the check constraint tying them together) go.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0032_backfill_authors'),
    ]

    operations = [
        migrations.RemoveConstraint(model_name='articleauthor', name='articleauthor_user_or_name'),
        migrations.AlterUniqueTogether(name='articleauthor', unique_together=set()),
        migrations.RemoveField(model_name='articleauthor', name='user'),
        migrations.RemoveField(model_name='articleauthor', name='name'),
        migrations.RemoveField(model_name='articleauthor', name='affiliation'),
        migrations.AlterField(
            model_name='articleauthor',
            name='author',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='bylines', to='articles.author',
            ),
        ),
        migrations.AlterUniqueTogether(name='articleauthor', unique_together={('article', 'author')}),
        migrations.AlterField(
            model_name='article',
            name='authors',
            field=models.ManyToManyField(related_name='articles', through='articles.ArticleAuthor', to='articles.author'),
        ),
    ]
