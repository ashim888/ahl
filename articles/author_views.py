"""Editorial management of Author byline profiles (/manage/authors/).

An Author is who gets credited on an article; a login account (users.User)
is optional and separate. Editors create authors here with no password
involved, and give one a login only when it's needed — the "Create user
account" action hands off to users:manage_account_create?author=<pk>, or
"Link existing account" attaches an account that already exists.
"""
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import AuthorForm
from .models import Article, Author

EDITORIAL_ROLES = User.EDITORIAL_ROLES


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AuthorManageListView(ListView):
    model = Author
    template_name = 'articles/manage/author_list.html'
    context_object_name = 'authors'
    paginate_by = 30

    def get_queryset(self):
        queryset = Author.objects.select_related('user').annotate(
            published_article_count=Count(
                'articles', filter=Q(articles__status=Article.Status.PUBLISHED), distinct=True,
            ),
            article_count=Count('articles', distinct=True),
        ).order_by('name')
        q = self.request.GET.get('q', '').strip()
        account = self.request.GET.get('account', '')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) | Q(affiliation__icontains=q) | Q(email__icontains=q) | Q(user__email__icontains=q),
            )
        if account == 'yes':
            queryset = queryset.filter(user__isnull=False)
        elif account == 'no':
            queryset = queryset.filter(user__isnull=True)
        if self.request.GET.get('active') == 'no':
            queryset = queryset.filter(is_active=False)
        elif self.request.GET.get('active') != 'all':
            queryset = queryset.filter(is_active=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_q'] = self.request.GET.get('q', '')
        context['selected_account'] = self.request.GET.get('account', '')
        context['selected_active'] = self.request.GET.get('active', '')
        # Accounts with no author profile yet — for the "Link existing account" picker.
        context['linkable_accounts'] = User.objects.filter(
            author_profile__isnull=True, is_active=True,
        ).order_by('first_name', 'last_name')
        return context


class AuthorFormMixin:
    model = Author
    form_class = AuthorForm
    template_name = 'articles/manage/author_form.html'

    def get_success_url(self):
        return reverse('articles:manage_author_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AuthorCreateView(AuthorFormMixin, CreateView):
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Author "{self.object.name}" added. They can now be credited on articles.')
        return response


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AuthorUpdateView(AuthorFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['bylines'] = self.object.bylines.select_related('article').order_by('-article__created_at')[:20]
        context['linkable_accounts'] = User.objects.filter(
            author_profile__isnull=True, is_active=True,
        ).order_by('first_name', 'last_name')
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'"{self.object.name}" updated.')
        return response


@role_required(*EDITORIAL_ROLES)
@require_POST
def author_toggle_active(request, pk):
    """Deactivate/reactivate — authors are never deleted from here, since
    their bylines must keep pointing at them (ArticleAuthor.author is
    PROTECT). An inactive author keeps existing bylines but drops out of the
    byline picker and loses the public author page.
    """
    author = get_object_or_404(Author, pk=pk)
    author.is_active = not author.is_active
    author.save(update_fields=['is_active'])
    messages.success(request, f'"{author.name}" {"reactivated" if author.is_active else "deactivated"}.')
    return redirect('articles:manage_author_list')


@role_required(*EDITORIAL_ROLES)
@require_POST
def author_link_account(request, pk):
    """Attach an existing login account to this author (or detach it with an
    empty selection). An account can back at most one author profile."""
    author = get_object_or_404(Author, pk=pk)
    user_pk = request.POST.get('user')
    if not user_pk:
        if author.user_id:
            messages.success(request, f'Account {author.user.email} unlinked from "{author.name}". Bylines are unchanged.')
            author.user = None
            author.save(update_fields=['user'])
        return redirect('articles:manage_author_update', pk=author.pk)
    user = get_object_or_404(User, pk=user_pk)
    if Author.objects.filter(user=user).exclude(pk=author.pk).exists():
        messages.error(request, f'{user.email} is already linked to another author profile.')
    else:
        author.user = user
        author.save(update_fields=['user'])
        messages.success(request, f'"{author.name}" is now linked to the account {user.email}.')
    return redirect('articles:manage_author_update', pk=author.pk)


@role_required(*EDITORIAL_ROLES)
@require_POST
def author_from_account(request, user_pk):
    """"Create author profile" on the Accounts screen — makes an existing
    login creditable on articles (reuses its profile if it already has one)."""
    user = get_object_or_404(User, pk=user_pk)
    author = Author.for_user(user)
    messages.success(request, f'Author profile ready for {user.get_full_name() or user.email}.')
    return redirect('articles:manage_author_update', pk=author.pk)
