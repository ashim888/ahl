from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView

from articles.models import Article

from .models import Issue


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
        ).prefetch_related('articleauthor_set__user')
        return context
