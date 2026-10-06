"""Keep Article.search_text current when something it's built from changes
outside Article.save() (articles/search.py)."""
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from sections.models import Section

from . import search
from .models import Article, ArticleAuthor, Author


@receiver(m2m_changed, sender=Article.keyword_tags.through)
def keywords_changed(sender, instance, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear') and isinstance(instance, Article):
        search.refresh([instance.pk])


@receiver(post_save, sender=ArticleAuthor)
@receiver(post_delete, sender=ArticleAuthor)
def byline_changed(sender, instance, **kwargs):
    search.refresh([instance.article_id])


@receiver(post_save, sender=Author)
def author_renamed(sender, instance, created, **kwargs):
    if not created:
        search.refresh(instance.bylines.values_list('article_id', flat=True))


@receiver(post_save, sender=Section)
def section_renamed(sender, instance, created, **kwargs):
    if not created:
        search.refresh(Article.objects.filter(section=instance).values_list('pk', flat=True))
