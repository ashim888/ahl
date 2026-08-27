from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from articles.models import Article
from issues.models import Issue
from users.decorators import role_required
from users.models import User

from .forms import EditorialBoardMemberForm
from .models import EditorialBoardMember

# Single source of truth is User.EDITORIAL_ROLES (see users/models.py).
EDITORIAL_ROLES = User.EDITORIAL_ROLES

ABOUT_TABS = ('about', 'board', 'policies')

# Policy content is honest about the OJS pivot (see ARCHITECTURE.md §1.1) —
# this platform doesn't claim to run its own peer review or accreditation
# memberships it doesn't actually hold.
POLICIES = [
    {
        'title': 'Peer Review Process',
        'sections': [
            {
                'heading': 'External Review via OJS',
                'body': 'Formal peer review for original research, review articles, case reports, and '
                        'methodology papers is conducted through OJS (Open Journal Systems), a dedicated '
                        'scholarly publishing platform. This site does not run its own submission or review '
                        'workflow for academic manuscripts.',
            },
            {
                'heading': 'After Acceptance',
                'body': 'Once a manuscript is accepted on OJS, the editorial team creates a brand-showcase '
                        'article here summarizing the accepted work, alongside our original health news and '
                        'commentary content.',
            },
        ],
    },
    {
        'title': 'Publication Ethics',
        'sections': [
            {
                'heading': 'Authorship',
                'body': 'All listed authors must have made a substantial contribution to the work and have '
                        'approved the final version published. Guest and ghost authorship are not permitted.',
            },
            {
                'heading': 'Conflicts of Interest',
                'body': 'Authors and editorial staff are expected to disclose financial relationships or '
                        'affiliations that could reasonably be seen to influence published content.',
            },
            {
                'heading': 'Corrections',
                'body': 'Errors identified after publication are corrected promptly, with a note on the '
                        'article indicating what changed and when.',
            },
        ],
    },
    {
        'title': 'Open Access Policy',
        'sections': [
            {
                'heading': 'Access Model',
                'body': 'Content is hybrid: news, commentary, editorials, letters, case reports, and short '
                        'communications are open access. Original research, review articles, and methodology '
                        'papers are subscription content by default, unless the editorial team marks an '
                        'individual article open access (e.g. an APC-funded article from OJS).',
            },
            {
                'heading': 'Subscriptions & APC',
                'body': 'Subscription and Article Processing Charge (APC) payment handling are planned for a '
                        'later phase of this platform and are not yet live — see the project roadmap for status.',
            },
        ],
    },
    {
        'title': 'Submission Guidelines',
        'sections': [
            {
                'heading': 'Academic Manuscripts',
                'body': 'Original research and other peer-reviewed manuscript types are submitted through OJS, '
                        'not this site. Contact the editorial team for the current OJS submission link.',
            },
            {
                'heading': 'News, Commentary & Opinion',
                'body': 'News tips, commentary, and opinion pitches can be sent to the editorial team at the '
                        'contact address on the About tab. These are reviewed editorially, not peer reviewed.',
            },
        ],
    },
]


class EditorialBoardPublicView(TemplateView):
    """Public page — /about/editorial-board/?tab=about|board|policies."""

    template_name = 'editorial_board/public_page.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tab = self.request.GET.get('tab', 'about')
        context['active_tab'] = tab if tab in ABOUT_TABS else 'about'
        context['members'] = EditorialBoardMember.objects.filter(is_active=True).select_related('user')
        context['article_types'] = Article.ArticleType.choices
        context['policies'] = POLICIES

        latest_issue = Issue.objects.filter(is_published=True).order_by('-created_at').first()
        context['publication_facts'] = [
            ('Latest issue', latest_issue.title if latest_issue else 'Not yet published'),
            ('ISSN', settings.JOURNAL_ISSN),
            ('Publisher', settings.JOURNAL_PUBLISHER),
            ('Peer review', 'Conducted externally via OJS'),
            ('Access model', 'Hybrid — open access and subscription, by article type'),
        ]

        tab_titles = {'about': 'About', 'board': 'Editorial Board', 'policies': 'Policies'}
        context['meta_title'] = f'{tab_titles[context["active_tab"]]} — {settings.JOURNAL_NAME}'
        context['meta_description'] = f'About {settings.JOURNAL_NAME} — editorial board, publication policies, and how to reach us.'
        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class BoardMemberManageListView(ListView):
    model = EditorialBoardMember
    template_name = 'editorial_board/manage/member_list.html'
    context_object_name = 'members'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset()
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
def member_move(request, pk, direction):
    """Swaps this member's display order with its neighbor. Orders start
    out defaulting to 0 for every new member (see EditorialBoardMember.order),
    which on its own gives no up/down to swap — so this also normalizes the
    whole list to sequential values first, making every move have a visible
    effect instead of silently no-opping on ties.
    """
    if direction not in ('up', 'down'):
        raise Http404

    members = list(EditorialBoardMember.objects.order_by('order', 'name', 'pk'))
    for index, member in enumerate(members):
        if member.order != index:
            member.order = index
            member.save(update_fields=['order'])

    member = get_object_or_404(EditorialBoardMember, pk=pk)
    current_index = member.order
    target_index = current_index - 1 if direction == 'up' else current_index + 1
    if 0 <= target_index < len(members):
        neighbor = members[target_index]
        member.order, neighbor.order = neighbor.order, member.order
        member.save(update_fields=['order'])
        neighbor.save(update_fields=['order'])

    return redirect('editorial_board:manage_member_list')


class BoardMemberFormMixin:
    def get_success_url(self):
        return reverse('editorial_board:manage_member_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class BoardMemberCreateView(BoardMemberFormMixin, CreateView):
    model = EditorialBoardMember
    form_class = EditorialBoardMemberForm
    template_name = 'editorial_board/manage/member_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.name}" added to the editorial board.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class BoardMemberUpdateView(BoardMemberFormMixin, UpdateView):
    model = EditorialBoardMember
    form_class = EditorialBoardMemberForm
    template_name = 'editorial_board/manage/member_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.name}" updated.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class BoardMemberDeleteView(DeleteView):
    model = EditorialBoardMember
    template_name = 'editorial_board/manage/member_confirm_delete.html'
    success_url = reverse_lazy('editorial_board:manage_member_list')

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object.name}" removed from the editorial board.')
        return super().form_valid(form)
