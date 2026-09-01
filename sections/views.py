from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import SectionForm
from .models import Section

# Single source of truth is User.EDITORIAL_ROLES (see users/models.py).
EDITORIAL_ROLES = User.EDITORIAL_ROLES


class SectionDetailView(DetailView):
    """Public landing page for a content section — mirrors
    articles/views.py:ArticleListView's shape (published-only, paginated,
    same card template style). A top-level section aggregates its own
    articles plus every child's; a leaf (child) section shows just its own.
    Article is imported locally, not at module level, so this app doesn't
    gain a hard import-time dependency on articles — matches the existing
    local-import pattern used elsewhere in this project for the same reason
    (e.g. ajna_health_lens/context_processors.py's `from issues.models import Issue`).
    """

    model = Section
    template_name = 'sections/section_detail.html'
    context_object_name = 'section'
    paginate_by = 10

    def get_queryset(self):
        return Section.objects.filter(is_active=True, link_url_name='')

    def get_context_data(self, **kwargs):
        from articles.models import Article

        context = super().get_context_data(**kwargs)
        section_ids = [self.object.pk] + list(self.object.children.values_list('pk', flat=True))
        articles = Article.objects.filter(
            section_id__in=section_ids, status=Article.Status.PUBLISHED,
        ).order_by('-is_pinned', '-publication_date', '-created_at').prefetch_related('articleauthor_set__user')
        page_obj = Paginator(articles, self.paginate_by).get_page(self.request.GET.get('page'))
        context['articles'] = page_obj
        context['page_obj'] = page_obj
        context['is_paginated'] = page_obj.has_other_pages()
        context['meta_title'] = f'{self.object.name} — {settings.JOURNAL_NAME}'
        context['meta_description'] = f'{self.object.name} coverage from {settings.JOURNAL_NAME}.'
        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class SectionManageListView(ListView):
    """Nav items are editorially curated and two levels deep by design —
    unlike every other manage list in this project, the realistic volume
    here never approaches "needs pagination," and a flat paginated table
    would also scatter parent/child rows across pages unpredictably (each
    level's `order` is normalized per sibling group, not globally — see
    section_move — so a single flat sort interleaves unrelated groups).
    Grouped display instead: top-level sections with their children nested
    directly beneath, no pagination.
    """

    model = Section
    template_name = 'sections/manage/section_list.html'
    context_object_name = 'sections'

    def get_queryset(self):
        queryset = Section.objects.filter(parent__isnull=True).prefetch_related('children')
        active = self.request.GET.get('active')
        if active == 'yes':
            queryset = queryset.filter(is_active=True)
        elif active == 'no':
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_active'] = self.request.GET.get('active', '')
        return context


@role_required(*EDITORIAL_ROLES)
@require_POST
def section_move(request, pk, direction):
    """Swaps this section's display order with its neighbor. Same
    normalize-then-swap pattern as editorial_board/views.py:member_move —
    orders default to 0 for every new section, which on its own gives
    nothing to swap, so this also normalizes the whole list to sequential
    values first, making every move have a visible effect instead of
    silently no-opping on ties. Top-level sections and sub-sections are
    ordered (and moved) independently of each other, not as one combined list.
    """
    if direction not in ('up', 'down'):
        raise Http404

    section = get_object_or_404(Section, pk=pk)
    siblings = list(Section.objects.filter(parent=section.parent).order_by('order', 'name', 'pk'))
    for index, sibling in enumerate(siblings):
        if sibling.order != index:
            sibling.order = index
            sibling.save(update_fields=['order'])

    section.refresh_from_db(fields=['order'])
    current_index = section.order
    target_index = current_index - 1 if direction == 'up' else current_index + 1
    if 0 <= target_index < len(siblings):
        neighbor = siblings[target_index]
        section.order, neighbor.order = neighbor.order, section.order
        section.save(update_fields=['order'])
        neighbor.save(update_fields=['order'])

    return redirect('sections:manage_section_list')


class SectionFormMixin:
    def get_success_url(self):
        return reverse('sections:manage_section_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class SectionCreateView(SectionFormMixin, CreateView):
    model = Section
    form_class = SectionForm
    template_name = 'sections/manage/section_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.name}" created.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class SectionUpdateView(SectionFormMixin, UpdateView):
    model = Section
    form_class = SectionForm
    template_name = 'sections/manage/section_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.name}" updated.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class SectionDeleteView(DeleteView):
    model = Section
    template_name = 'sections/manage/section_confirm_delete.html'
    success_url = reverse_lazy('sections:manage_section_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['child_count'] = self.object.children.count()
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object.name}" deleted.')
        return super().form_valid(form)
