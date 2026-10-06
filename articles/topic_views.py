"""/topics/ and /topics/<slug>/ — see articles/topics.py."""
from django.conf import settings
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from .models import Article, Keyword, KeywordFollow
from .topics import INDEX_MIN_ARTICLES, hashtag, public_topics, related_topics, trending_topics

ARTICLES_PER_PAGE = 12


def topic_list(request):
    """Every public topic, A–Z by first letter, with trending ones on top."""
    topics = list(public_topics().order_by('name'))
    groups: dict[str, list] = {}
    for topic in topics:
        first = topic.name[:1].upper()
        groups.setdefault(first if first.isascii() and first.isalpha() else first or '#', []).append(topic)
    return render(request, 'articles/topic_list.html', {
        'trending': trending_topics(12),
        'groups': sorted(groups.items(), key=lambda item: (not item[0].isascii(), item[0])),
        'topic_count': len(topics),
        'meta_title': _('Topics — %(site)s') % {'site': settings.JOURNAL_NAME},
        'meta_description': _('Browse %(site)s by topic: every health subject we cover, from dengue to mental health.') % {
            'site': settings.JOURNAL_NAME},
    })


def topic_detail(request, slug):
    """One topic: its stories (newest first), related topics, follow."""
    keyword = get_object_or_404(Keyword, slug=slug)
    articles = (Article.objects.filter(status=Article.Status.PUBLISHED, keyword_tags=keyword)
                .order_by('-published_at', '-created_at')
                .select_related('section').prefetch_related('articleauthor_set__author__user', 'keyword_tags'))
    total = articles.count()
    if not total:
        raise Http404
    page = Paginator(articles, ARTICLES_PER_PAGE).get_page(request.GET.get('page'))
    tag = hashtag(keyword.name)
    return render(request, 'articles/topic_detail.html', {
        'keyword': keyword, 'hashtag': tag, 'page_obj': page, 'articles': page.object_list, 'total': total,
        'related': related_topics(keyword),
        'is_following': request.user.is_authenticated and KeywordFollow.objects.filter(
            user=request.user, keyword=keyword).exists(),
        'meta_title': _('%(tag)s — %(name)s news — %(site)s') % {'tag': tag, 'name': keyword.name,
                                                               'site': settings.JOURNAL_NAME},
        'meta_description': _('%(count)s stories about %(name)s from %(site)s — the latest news, research and explainers.') % {
            'count': total, 'name': keyword.name, 'site': settings.JOURNAL_NAME},
        'meta_robots': 'index, follow' if total >= INDEX_MIN_ARTICLES and page.number == 1 else 'noindex, follow',
    })
