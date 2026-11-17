from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
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

# Policies follow the platform's vision (Ajna_vision.docx, Nov 2026): an
# evidence-based health news and knowledge platform, with a peer-reviewed
# journal as one part of it. Still honest about the OJS pivot (see
# ARCHITECTURE.md §1.1): this site doesn't run its own peer review, and the
# text claims no registrations or memberships it doesn't hold — it states
# the standards and frameworks we work to. Nepali in locale/ne (gettext_lazy).
POLICIES = [
    {
        'title': gettext_lazy('Editorial Standards & Fact-Checking'),
        'sections': [
            {
                'heading': gettext_lazy('Sources We Rely On'),
                'body': gettext_lazy('Our reporting starts from peer-reviewed research and authoritative institutions: the '
                              'World Health Organization (WHO), Nepal Health Research Council (NHRC), Ministry of Health '
                              'and Population (MoHP), Medical Education Commission (MEC), PubMed/MEDLINE, and journals '
                              'such as The Lancet, BMJ and NEJM. A single study, a press release or a social media post '
                              'is not treated as settled evidence on its own.'),
            },
            {
                'heading': gettext_lazy('Fact-Checking'),
                'body': gettext_lazy('Every story is checked by an editor before publication: figures against their source, '
                              'quotes against the speaker, and medical claims against the evidence. Stories that need '
                              'specialist judgement are read by someone with that expertise.'),
            },
            {
                'heading': gettext_lazy('Citation & Attribution'),
                'body': gettext_lazy('We say where information comes from. Articles list their references, and readers can '
                              'follow each one back to the original study, report or dataset.'),
            },
            {
                'heading': gettext_lazy('Plain Language'),
                'body': gettext_lazy('We translate technical evidence into clear, practical language, in Nepali and English, '
                              'without overstating what a study shows. Where the evidence is uncertain or still '
                              'developing, we say so.'),
            },
        ],
    },
    {
        # The verdict scale used by fact checks (Article.Verdict); the verdict box links here.
        'title': gettext_lazy('How We Rate Claims'),
        'sections': [
            {
                'heading': gettext_lazy('What We Check'),
                'body': gettext_lazy('We check health claims that are spreading widely or could cause harm if believed: '
                                     'remedies, vaccine rumours, outbreak scares, statements by public figures. Readers '
                                     'can send us claims to check.'),
            },
            {
                'heading': gettext_lazy('False / Mostly false'),
                'body': gettext_lazy('False: the evidence clearly contradicts the claim. Mostly false: a small part may '
                                     'be accurate, but the main point is wrong.'),
            },
            {
                'heading': gettext_lazy('Misleading'),
                'body': gettext_lazy('The facts may be real, but they are presented in a way that gives a wrong '
                                     'impression: out of context, exaggerated, or missing something important.'),
            },
            {
                'heading': gettext_lazy('Unproven'),
                'body': gettext_lazy('There is not yet enough good evidence to say whether the claim is true or false.'),
            },
            {
                'heading': gettext_lazy('Mostly true / True'),
                'body': gettext_lazy('Mostly true: accurate, but needs a clarification or extra detail. True: the '
                                     'evidence supports the claim.'),
            },
            {
                'heading': gettext_lazy('Updates'),
                'body': gettext_lazy('If new evidence changes a verdict, we update the fact check and say what changed '
                                     'and when.'),
            },
        ],
    },
    {
        'title': gettext_lazy('Independence & Ethics'),
        'sections': [
            {
                'heading': gettext_lazy('Editorial Independence'),
                'body': gettext_lazy('Editorial decisions are made by the editorial team alone. Advertisers, sponsors, '
                              'partners and funders have no say over what we cover or how. Advertising is always '
                              'labelled as such.'),
            },
            {
                'heading': gettext_lazy('Conflicts of Interest'),
                'body': gettext_lazy('Authors, editors and editorial board members disclose financial relationships or '
                              'affiliations that could reasonably be seen to influence what they write or review.'),
            },
            {
                'heading': gettext_lazy('Authorship'),
                'body': gettext_lazy('Everyone listed as an author has made a substantial contribution to the work and '
                              'approved the published version. Guest and ghost authorship are not permitted.'),
            },
            {
                'heading': gettext_lazy('Health Information'),
                'body': gettext_lazy('Our content is for information and education. It does not replace advice from a '
                              'qualified health professional about your own health.'),
            },
        ],
    },
    {
        'title': gettext_lazy('Corrections'),
        'sections': [
            {
                'heading': gettext_lazy('How We Correct'),
                'body': gettext_lazy('Errors found after publication are corrected promptly, with a note on the article '
                              'saying what changed and when. All corrections are listed on our Corrections page.'),
            },
            {
                'heading': gettext_lazy('Reporting an Error'),
                'body': gettext_lazy('If you spot a mistake, write to the editorial team at the contact address on the '
                              'About tab.'),
            },
        ],
    },
    {
        'title': gettext_lazy('Peer-Reviewed Journal'),
        'sections': [
            {
                'heading': gettext_lazy('The Journal'),
                'body': gettext_lazy('Alongside our news and explainers we publish a peer-reviewed scientific journal, '
                              'prioritising research on Nepal\'s healthcare and medical education systems, in Nepali '
                              'and English.'),
            },
            {
                'heading': gettext_lazy('Peer Review via OJS'),
                'body': gettext_lazy('Submission and peer review for original research, review articles, case reports and '
                              'methodology papers take place on OJS (Open Journal Systems), a dedicated scholarly '
                              'publishing platform, not on this site. Independent experts review each manuscript '
                              'before it is accepted.'),
            },
            {
                'heading': gettext_lazy('After Acceptance'),
                'body': gettext_lazy('Accepted papers are published here with a plain-language summary, so their findings '
                              'reach health workers, policymakers and the public, not only researchers.'),
            },
        ],
    },
    {
        'title': gettext_lazy('Access'),
        'sections': [
            {
                'heading': gettext_lazy('What Is Free'),
                'body': gettext_lazy('News, commentary, editorials, letters, case reports and short communications are free '
                              'to read. The summary of every article is always free.'),
            },
            {
                'heading': gettext_lazy('Subscriber Content'),
                'body': gettext_lazy('Original research, review articles and methodology papers are for subscribers by '
                              'default, unless the editorial team makes an individual article free. Some special '
                              'reports can also be bought one at a time.'),
            },
        ],
    },
    {
        'title': gettext_lazy('Contributing'),
        'sections': [
            {
                'heading': gettext_lazy('Research Manuscripts'),
                'body': gettext_lazy('Original research and other peer-reviewed manuscript types are submitted through OJS. '
                              'Contact the editorial team for the current submission link. Students and early-career '
                              'researchers are welcome to submit.'),
            },
            {
                'heading': gettext_lazy('Story Ideas & Opinion'),
                'body': gettext_lazy('Health professionals, researchers, students and readers can pitch news tips, '
                              'explainers and opinion pieces. These are reviewed by our editors, not peer reviewed.'),
            },
            {
                'heading': gettext_lazy('Student Research'),
                'body': gettext_lazy('Students and early-career researchers can share their own thesis, project or paper '
                              'through the student track of the pitch form ("Student research" in the footer). An editor '
                              'helps turn it into a plain-language story for the public.'),
            },
        ],
    },
    {
        'title': gettext_lazy('Governance & Compliance'),
        'sections': [
            {
                'heading': gettext_lazy('Frameworks We Work Within'),
                'body': gettext_lazy('We aim to operate in line with the Department of Information and Broadcasting, Press '
                              'Council Nepal and its code of conduct, the Ministry of Health and Population, Nepal '
                              'Health Research Council, Medical Education Commission, the Right to Information Act '
                              '2064, the Electronic Transactions Act 2063, and Nepal\'s other media and digital '
                              'governance frameworks.'),
            },
        ],
    },
]


# The vision's public health priorities (Objective 4), plus medical
# education and research (Objective 5), for the About tab.
FOCUS_AREAS = [
    gettext_lazy('Maternal and child health'), gettext_lazy('Mental health'), gettext_lazy('Nutrition'),
    gettext_lazy('Communicable diseases'), gettext_lazy('Non-communicable diseases'),
    gettext_lazy('Medicines and pharmaceutical awareness'), gettext_lazy('Adolescent health'),
    gettext_lazy('Emergency health information'), gettext_lazy('Health policy and health system governance'),
    gettext_lazy('Medical education and research'),
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
        context['focus_areas'] = FOCUS_AREAS

        latest_issue = Issue.objects.filter(is_published=True).order_by('-created_at').first()
        facts = [
            (_('Latest issue'), latest_issue.title if latest_issue else _('Not yet published')),
            ('ISSN', settings.JOURNAL_ISSN),
            (_('Publisher'), settings.JOURNAL_PUBLISHER if settings.JOURNAL_PUBLISHER_CONFIRMED else ''),
            (_('Languages'), _('Nepali and English')),
            (_('Journal'), _('Peer-reviewed, published quarterly')),
            (_('Peer review'), _('Done independently, through our journal system (OJS)')),
            (_('Access'), _('Free, subscribers only, or a single purchase: decided story by story')),
        ]
        # A fact with no real value (no ISSN yet, publisher unconfirmed) is left out, not shown blank.
        context['publication_facts'] = [(label, value) for label, value in facts if value]

        tab_titles = {'about': _('About'), 'board': _('Editorial Board'), 'policies': _('Policies')}
        context['meta_title'] = f'{tab_titles[context["active_tab"]]} — {settings.JOURNAL_NAME}'
        context['meta_description'] = _(
            'About %(site)s: an evidence-based health news and knowledge platform for Nepal. '
            'Our vision, mission, editorial board, policies, and how to reach us.') % {'site': settings.JOURNAL_NAME}
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
