from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from articles.models import Article
from users.decorators import role_required
from users.models import User

from .forms import IssueForm
from .models import Issue

# Matches EDITORIAL_ROLES in articles/views.py, admin_custom/views.py, editorial_board/views.py, training/views.py.
EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)


class IssueListView(ListView):
    model = Issue
    template_name = 'issues/issue_list.html'
    context_object_name = 'issues'
    paginate_by = 10

    def get_queryset(self):
        return Issue.objects.filter(is_published=True)


class IssueDetailView(DetailView):
    model = Issue
    template_name = 'issues/issue_detail.html'
    context_object_name = 'issue'

    def get_object(self, queryset=None):
        return get_object_or_404(
            Issue, volume=self.kwargs['volume'], number=self.kwargs['number'], is_published=True,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['issue_articles'] = self.object.articles.filter(
            status=Article.Status.PUBLISHED,
        ).order_by('-created_at').prefetch_related('articleauthor_set__user')
        return context


# -- Editorial issue management (CRUD, not public browsing) ----------------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class IssueManageListView(ListView):
    """All issues regardless of publish status, for editorial management."""

    model = Issue
    template_name = 'issues/manage/issue_list.html'
    context_object_name = 'issues'
    paginate_by = 30

    def get_queryset(self):
        return Issue.objects.order_by('-volume', '-number')


class IssueFormMixin:
    def get_success_url(self):
        return reverse('issues:manage_issue_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class IssueCreateView(IssueFormMixin, CreateView):
    model = Issue
    form_class = IssueForm
    template_name = 'issues/manage/issue_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance}" created.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class IssueUpdateView(IssueFormMixin, UpdateView):
    model = Issue
    form_class = IssueForm
    template_name = 'issues/manage/issue_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance}" updated.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class IssueDeleteView(DeleteView):
    model = Issue
    template_name = 'issues/manage/issue_confirm_delete.html'
    success_url = reverse_lazy('issues:manage_issue_list')

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object}" deleted.')
        return super().form_valid(form)
