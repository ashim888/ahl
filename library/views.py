from django.conf import settings
from django.contrib import messages
from django.db.models import Count, F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from articles.models import Article, Keyword
from articles.seo import breadcrumb_list_structured_data
from users.decorators import role_required
from users.models import User

import json

from django.shortcuts import render
from django.utils.translation import get_language

from .forms import GlossaryTermForm, ResourceForm
from .models import GlossaryTerm, Resource
from .queries import glossary_matching, matching

EDITORIAL_ROLES = User.EDITORIAL_ROLES


class ResourceListView(ListView):
    """/library/ — filter by type, language and topic; search title, summary
    and source."""

    template_name = 'library/resource_list.html'
    context_object_name = 'resources'
    paginate_by = 20

    def get_queryset(self):
        queryset = Resource.objects.filter(is_published=True)
        params = self.request.GET
        self.selected_type = params.get('type', '') if params.get('type') in Resource.ResourceType.values else ''
        self.selected_language = params.get('lang', '') if params.get('lang') in Resource.Language.values else ''
        self.query = params.get('q', '').strip()[:100]
        self.topic = Keyword.objects.filter(slug=params.get('topic', '')).first() if params.get('topic') else None
        if self.selected_type:
            queryset = queryset.filter(resource_type=self.selected_type)
        if self.selected_language:
            # A bilingual resource counts as both Nepali and English.
            queryset = queryset.filter(language__in=[self.selected_language, Resource.Language.BOTH])
        if self.topic:
            queryset = queryset.filter(keyword_tags=self.topic)
        if self.query:
            # Every word, anywhere: "dengue guideline" finds "Guideline for dengue…".
            queryset = matching(queryset, self.query)
        return queryset.order_by(F('year').desc(nulls_last=True), '-created_at').prefetch_related('keyword_tags')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = dict(
            Resource.objects.filter(is_published=True).values_list('resource_type').annotate(n=Count('pk'))
        )
        context.update({
            'type_choices': [(value, label, counts.get(value, 0)) for value, label in Resource.ResourceType.choices],
            'language_choices': [c for c in Resource.Language.choices if c[0] != Resource.Language.BOTH],
            'selected_type': self.selected_type,
            'selected_language': self.selected_language,
            'query': self.query,
            'topic': self.topic,
            'total_count': sum(counts.values()),
            'is_filtered': bool(self.selected_type or self.selected_language or self.query or self.topic),
            'meta_title': f'{_("Health Library")} — {settings.JOURNAL_NAME}',
            'meta_description': (
                f'Research papers, policy documents, government reports, guidelines, training material and data '
                f'on health in Nepal, collected by {settings.JOURNAL_NAME}. Free to read and download.'
            ),
        })
        return context


class ResourceDetailView(DetailView):
    template_name = 'library/resource_detail.html'
    context_object_name = 'resource'

    def get_object(self, queryset=None):
        return get_object_or_404(Resource, slug=self.kwargs['slug'], is_published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource = self.object
        context['topics'] = list(resource.keyword_tags.all())
        context['related_articles'] = resource.related_articles.filter(
            status=Article.Status.PUBLISHED).order_by('-published_at')[:6]
        # More from the library: shared topics first, then the same type.
        more = Resource.objects.filter(is_published=True).exclude(pk=resource.pk)
        if context['topics']:
            more = more.annotate(shared=Count('keyword_tags', filter=Q(keyword_tags__in=context['topics'])))
            more = more.order_by('-shared', '-created_at')
        else:
            more = more.filter(resource_type=resource.resource_type)
        context['more_resources'] = more[:4]
        context['meta_title'] = f'{resource.title} — {_("Health Library")} — {settings.JOURNAL_NAME}'
        context['meta_description'] = resource.summary[:200]
        context['breadcrumb_json'] = breadcrumb_list_structured_data([
            ('Home', self.request.build_absolute_uri(reverse('articles:home'))),
            ('Health Library', self.request.build_absolute_uri(reverse('library:resource_list'))),
            (resource.title, None),
        ])
        return context


@require_GET
def resource_download(request, slug):
    """Counts the download, then sends the reader to the file or the
    official link. Unpublished resources 404 here too."""
    resource = get_object_or_404(Resource, slug=slug, is_published=True)
    target = resource.file.url if resource.file else resource.external_url
    if not target:
        raise Http404
    Resource.objects.filter(pk=resource.pk).update(download_count=F('download_count') + 1)
    return redirect(target)


# -- Glossary ----------------------------------------------------------------

def glossary_list(request):
    """/library/glossary/: every published term, A–Z (Devanagari first, then
    Latin), with search across names, other names and definitions."""
    terms = GlossaryTerm.objects.filter(is_published=True)
    letters = sorted({t.index_letter for t in terms}, key=lambda c: (c.isascii(), c))
    query = request.GET.get('q', '').strip()[:100]
    letter = request.GET.get('letter', '')
    if query:
        terms = glossary_matching(terms, query)
    terms = sorted(terms, key=lambda t: (t.index_letter.isascii(), t.primary_term.lower()))
    if letter and not query:
        terms = [t for t in terms if t.index_letter == letter]
    groups = {}
    for term in terms:
        groups.setdefault(term.index_letter, []).append(term)
    language = get_language() or 'ne'
    for term in terms:
        term.shown_definition = term.definition_for(language)
    return render(request, 'library/glossary_list.html', {
        'groups': list(groups.items()), 'letters': letters, 'selected_letter': letter if not query else '',
        'query': query, 'result_count': len(terms),
        'meta_title': f'{_("Health Glossary")} — {settings.JOURNAL_NAME}',
        'meta_description': (f'Medical and public-health terms explained in plain Nepali and English, '
                             f'from {settings.JOURNAL_NAME}.'),
    })


def glossary_detail(request, slug):
    term = get_object_or_404(GlossaryTerm, slug=slug, is_published=True)
    language = get_language() or 'ne'
    # Definitions: the reader's language first, then the other one if written.
    definitions = [(code, text) for code, text in (('ne', term.definition_ne), ('en', term.definition_en)) if text]
    definitions.sort(key=lambda d: d[0] != language)
    # Our articles that mention the term (site search, articles/search.py).
    from articles.search import search_ids

    published_articles = Article.objects.filter(status=Article.Status.PUBLISHED)
    ids = []
    for name in [term.term_ne, term.term_en]:
        if name:
            ids += [pk for pk in search_ids(published_articles, name, limit=6) if pk not in ids]
    by_id = Article.objects.in_bulk(ids[:6])
    mentions = [by_id[pk] for pk in ids[:6] if pk in by_id]
    return render(request, 'library/glossary_detail.html', {
        'term': term, 'definitions': definitions, 'mentions': mentions,
        'related_terms': term.related_terms.filter(is_published=True),
        'topics': term.keyword_tags.all(),
        'meta_title': f'{term.display_name} — {_("Health Glossary")} — {settings.JOURNAL_NAME}',
        'meta_description': term.definition_for(language)[:200],
        'defined_term_json': json.dumps({
            '@context': 'https://schema.org', '@type': 'DefinedTerm',
            'name': term.primary_term, 'alternateName': [n for n in term.names if n != term.primary_term] or None,
            'description': term.definition_for(language),
            'url': request.build_absolute_uri(term.get_absolute_url()),
            'inDefinedTermSet': request.build_absolute_uri(reverse('library:glossary_list')),
        }, ensure_ascii=False).replace('<', '\\u003c'),  # safe inside <script>, whatever editors type
    })


# -- Editorial management ---------------------------------------------------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ResourceManageListView(ListView):
    template_name = 'library/manage/resource_list.html'
    context_object_name = 'resources'
    paginate_by = 30

    def get_queryset(self):
        queryset = Resource.objects.order_by('-created_at')
        params = self.request.GET
        if params.get('published') == 'yes':
            queryset = queryset.filter(is_published=True)
        elif params.get('published') == 'no':
            queryset = queryset.filter(is_published=False)
        if params.get('type') in Resource.ResourceType.values:
            queryset = queryset.filter(resource_type=params['type'])
        if params.get('q'):
            queryset = queryset.filter(Q(title__icontains=params['q']) | Q(source__icontains=params['q']))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['type_choices'] = Resource.ResourceType.choices
        context['selected_published'] = self.request.GET.get('published', '')
        context['selected_type'] = self.request.GET.get('type', '')
        context['query'] = self.request.GET.get('q', '')
        return context


class ResourceFormMixin:
    model = Resource
    form_class = ResourceForm
    template_name = 'library/manage/resource_form.html'

    def get_success_url(self):
        return reverse('library:manage_resource_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ResourceCreateView(ResourceFormMixin, CreateView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(is_create=True, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f'"{form.instance}" added to the library.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ResourceUpdateView(ResourceFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(is_create=False, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance}" updated.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ResourceDeleteView(DeleteView):
    model = Resource
    template_name = 'library/manage/resource_confirm_delete.html'
    context_object_name = 'resource'
    success_url = reverse_lazy('library:manage_resource_list')

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object}" deleted.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class GlossaryManageListView(ListView):
    template_name = 'library/manage/glossary_list.html'
    context_object_name = 'terms'
    paginate_by = 50

    def get_queryset(self):
        queryset = GlossaryTerm.objects.order_by('term_ne', 'term_en')
        if self.request.GET.get('q'):
            queryset = glossary_matching(queryset, self.request.GET['q'], definitions=False)
        if self.request.GET.get('published') == 'no':
            queryset = queryset.filter(is_published=False)
        return queryset

    def get_context_data(self, **kwargs):
        return super().get_context_data(query=self.request.GET.get('q', ''),
                                         selected_published=self.request.GET.get('published', ''), **kwargs)


class GlossaryFormMixin:
    model = GlossaryTerm
    form_class = GlossaryTermForm
    template_name = 'library/manage/glossary_form.html'

    def get_success_url(self):
        if '_addanother' in self.request.POST:
            return reverse('library:manage_glossary_create')
        return reverse('library:manage_glossary_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class GlossaryCreateView(GlossaryFormMixin, CreateView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(is_create=True, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f'"{form.instance}" added to the glossary.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class GlossaryUpdateView(GlossaryFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(is_create=False, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance}" updated.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class GlossaryDeleteView(DeleteView):
    model = GlossaryTerm
    template_name = 'library/manage/glossary_confirm_delete.html'
    context_object_name = 'term'
    success_url = reverse_lazy('library:manage_glossary_list')

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object}" deleted.')
        return super().form_valid(form)
