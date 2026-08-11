from django.conf import settings
from django.contrib import messages
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from articles.models import Article
from issues.models import Issue
from users.decorators import role_required
from users.models import User

from .forms import EditorialBoardMemberForm
from .models import EditorialBoardMember

# Matches EDITORIAL_ROLES in articles/views.py and admin_custom/views.py —
# editorial board management is an Editor/EiC/Admin capability.
EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)

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

        latest_issue = Issue.objects.filter(is_published=True).order_by('-publication_date').first()
        context['publication_facts'] = [
            ('Current volume', f'Vol. {latest_issue.volume}, Issue {latest_issue.number}' if latest_issue else 'Not yet published'),
            ('ISSN', settings.JOURNAL_ISSN),
            ('Publisher', settings.JOURNAL_PUBLISHER),
            ('Peer review', 'Conducted externally via OJS'),
            ('Access model', 'Hybrid — open access and subscription, by article type'),
        ]
        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class BoardMemberManageListView(ListView):
    model = EditorialBoardMember
    template_name = 'editorial_board/manage/member_list.html'
    context_object_name = 'members'
    paginate_by = 30


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
