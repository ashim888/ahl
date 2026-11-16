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

from .forms import ResourceForm
from .models import Resource
from .queries import matching

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
