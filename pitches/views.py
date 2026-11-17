from django.conf import settings
from django.utils.translation import gettext as _
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import linebreaks
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView
from django_ratelimit.decorators import ratelimit

from ajna_health_lens.mail import send_templated_email
from articles.models import Article, ArticleAuthor, Author
from users.decorators import role_required
from users.models import User

from .forms import ClaimForm, PitchDecisionForm, StoryPitchForm
from .models import StoryPitch
from .signals import SUBMITTER_FROM_EMAIL

# Revised (August 2026, twice): first opened from verified_author-only to
# any authenticated account, then dropped the login requirement entirely —
# no account needed at all to pitch a story. A logged-out visitor's contact
# info is captured directly on the pitch instead (submitter_name/
# submitter_email, see pitches/models.py) so the editorial team can still
# follow up. That openness is exactly why real CAPTCHA (pitches/captcha.py)
# exists — rate limiting keys on IP, not user, since there's often no user.
# Reviewing pitches is editorial content triage, same boundary as Article
# CRUD — not the narrower EiC/Admin-only verification-queue boundary.
EDITORIAL_ROLES = User.EDITORIAL_ROLES


@method_decorator(ratelimit(key='ip', rate='10/h', method='POST', block=True), name='dispatch')
class PitchCreateView(CreateView):
    model = StoryPitch
    form_class = StoryPitchForm
    template_name = 'pitches/pitch_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['turnstile_site_key'] = settings.TURNSTILE_SITE_KEY
        context['student_track'] = self.request.GET.get('track') == 'student'
        context['meta_description'] = _(
            'Got a health story Nepal should hear? Pitch it to the editors of %(site)s — '
            'no account needed, and we reply to every pitch.') % {'site': settings.JOURNAL_NAME}
        return context

    def form_valid(self, form):
        if self.request.user.is_authenticated:
            form.instance.submitter = self.request.user
        response = super().form_valid(form)
        self.request.session['pitch_thanks'] = self.object.pk
        return response

    def get_success_url(self):
        return reverse('pitches:pitch_thanks')


class ClaimCreateView(PitchCreateView):
    """/pitches/claim/ — a reader sends a health claim to check (linked from
    /fact-checks/). Lands in the pitch queue as a "Claim to check"."""

    form_class = ClaimForm
    template_name = 'pitches/claim_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meta_description'] = _(
            'Seen a health claim you are not sure about? Send it to the editors of %(site)s to check.') % {
            'site': settings.JOURNAL_NAME}
        return context


def pitch_thanks(request):
    """/pitches/thanks/ — the confirmation after sending a pitch: what
    happens next, and where to follow it (signed-in) or which email we'll
    reply to (anonymous). Shown once per pitch; afterwards it's generic."""
    pitch = None
    pitch_pk = request.session.pop('pitch_thanks', None)
    if pitch_pk:
        pitch = StoryPitch.objects.filter(pk=pitch_pk).first()
    return render(request, 'pitches/pitch_thanks.html', {'pitch': pitch})


@method_decorator(login_required, name='dispatch')
class MyPitchesListView(ListView):
    model = StoryPitch
    template_name = 'pitches/my_pitches.html'
    context_object_name = 'pitches'
    paginate_by = 20

    def get_queryset(self):
        queryset = StoryPitch.objects.filter(submitter=self.request.user).select_related('article')
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = StoryPitch.Status.choices
        context['selected_status'] = self.request.GET.get('status', '')
        return context


# -- Editorial review queue -------------------------------------------------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class PitchQueueListView(ListView):
    """Parallel to users:verification_queue — a queue of things editorial
    staff need to act on, this time story pitches instead of new accounts.
    """

    model = StoryPitch
    template_name = 'pitches/manage/pitch_queue.html'
    context_object_name = 'pitches'
    paginate_by = 30

    def get_queryset(self):
        queryset = StoryPitch.objects.select_related('submitter').order_by('-created_at')
        status = self.request.GET.get('status')
        q = self.request.GET.get('q')
        if status:
            queryset = queryset.filter(status=status)
        else:
            queryset = queryset.exclude(status__in=[StoryPitch.Status.ACCEPTED, StoryPitch.Status.REJECTED, StoryPitch.Status.PUBLISHED])
        if self.request.GET.get('student'):
            queryset = queryset.filter(is_student=True)
        if self.request.GET.get('claims'):
            queryset = queryset.filter(kind=StoryPitch.Kind.CLAIM)
        if q:
            queryset = queryset.filter(
                Q(title__icontains=q) | Q(submitter_name__icontains=q) | Q(submitter_email__icontains=q)
                | Q(submitter__first_name__icontains=q) | Q(submitter__last_name__icontains=q) | Q(submitter__email__icontains=q),
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = StoryPitch.Status.choices
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_q'] = self.request.GET.get('q', '')
        context['student_only'] = bool(self.request.GET.get('student'))
        context['claims_only'] = bool(self.request.GET.get('claims'))
        return context


@role_required(*EDITORIAL_ROLES)
def pitch_detail(request, pk):
    pitch = get_object_or_404(StoryPitch.objects.select_related('submitter', 'article'), pk=pk)
    if request.method == 'POST':
        previous_feedback = pitch.editor_feedback
        form = PitchDecisionForm(request.POST, instance=pitch)
        if form.is_valid():
            form.save()
            # This form only ever changes editor_feedback, not status — the
            # pre_save status-change signal (pitches/signals.py) never fires
            # for it, so without this, feedback left here (independent of
            # an accept/reject/in-review decision — see pitch_detail.html's
            # separate "Save feedback" form) went completely unnotified.
            # Only fires on an actual change, not every re-save of the same
            # text, and only if there's something to actually tell them.
            if pitch.editor_feedback and pitch.editor_feedback != previous_feedback and pitch.contact_email:
                send_templated_email(
                    subject=f'A note on your {pitch.noun}: "{pitch.title}"',
                    template='pitches/email/pitch_feedback',
                    context={'pitch': pitch},
                    recipient_list=[pitch.contact_email],
                    from_email=SUBMITTER_FROM_EMAIL,
                )
            messages.success(request, 'Feedback saved.')
            return redirect('pitches:manage_pitch_detail', pk=pitch.pk)
    else:
        form = PitchDecisionForm(instance=pitch)
    return render(request, 'pitches/manage/pitch_detail.html', {'pitch': pitch, 'form': form})


@role_required(*EDITORIAL_ROLES)
@require_POST
def pitch_decide(request, pk, decision):
    if decision not in ('start_review', 'accept', 'reject'):
        raise PermissionDenied

    pitch = get_object_or_404(StoryPitch, pk=pk)

    if decision == 'start_review':
        pitch.status = StoryPitch.Status.IN_REVIEW
        pitch.reviewed_by = request.user
        pitch.save()
        messages.success(request, f'"{pitch.title}" marked in review.')
    elif decision == 'reject':
        pitch.status = StoryPitch.Status.REJECTED
        pitch.reviewed_by = request.user
        pitch.decided_at = timezone.now()
        pitch.save()
        messages.success(request, f'"{pitch.title}" rejected.')
    elif decision == 'accept':
        article = article_from_pitch(pitch)
        pitch.article = article
        pitch.status = StoryPitch.Status.ACCEPTED
        pitch.reviewed_by = request.user
        pitch.decided_at = timezone.now()
        pitch.save()
        messages.success(request, f'"{pitch.title}" accepted — draft article created, finish it up in Articles.')
        return redirect('articles:manage_article_update', slug=article.slug)

    return redirect('pitches:manage_pitch_detail', pk=pitch.pk)


@role_required(*EDITORIAL_ROLES)
@require_POST
def pitch_bulk_decide(request):
    """Same accept/reject logic as pitch_decide, applied to every checked
    row at once. Unlike the single-pitch accept (which redirects straight
    into the new draft article), a bulk accept can create several articles
    at once, so there's no single one to jump to — it redirects back to the
    queue, same as bulk reject.
    """
    decision = request.POST.get('decision')
    if decision not in ('accept', 'reject'):
        raise PermissionDenied

    pks = request.POST.getlist('pks')
    pitches = StoryPitch.objects.filter(pk__in=pks).exclude(
        status__in=[StoryPitch.Status.ACCEPTED, StoryPitch.Status.REJECTED, StoryPitch.Status.PUBLISHED],
    )
    decided_count = 0
    for pitch in pitches:
        if decision == 'reject':
            pitch.status = StoryPitch.Status.REJECTED
            pitch.reviewed_by = request.user
            pitch.decided_at = timezone.now()
            pitch.save()
        elif decision == 'accept':
            article = article_from_pitch(pitch)
            pitch.article = article
            pitch.status = StoryPitch.Status.ACCEPTED
            pitch.reviewed_by = request.user
            pitch.decided_at = timezone.now()
            pitch.save()
        decided_count += 1

    if decided_count:
        messages.success(request, f'{decided_count} pitch(es) {decision}ed.')
    else:
        messages.error(request, 'No eligible pitches were selected.')
    return redirect('pitches:manage_pitch_queue')


def article_from_pitch(pitch):
    """The draft article an accepted pitch becomes. A story pitch: a news
    draft, its submitter (if signed in) as the byline. A reader's claim: a
    Fact check draft with the claim filled in; the reader isn't its author.

    pitch.body is plain text from a public, low-trust form, while
    Article.html_content is trusted editor HTML rendered unescaped
    ({{ chunk|safe }} in article_detail.html). linebreaks() escapes it, so a
    submitter's <script> can't run for the reviewing editor or, once
    published, for every reader. The slug is left blank: Article.save()
    makes one from the title."""
    if pitch.is_claim:
        return Article.objects.create(
            title=pitch.title, article_type=Article.ArticleType.FACT_CHECK, status=Article.Status.DRAFT,
            fact_check_claim=pitch.summary, fact_check_claim_source=' '.join(pitch.body.split())[:200],
            fact_check_claim_url=pitch.claim_url,
        )
    article = Article.objects.create(
        title=pitch.title, abstract=pitch.summary,
        article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
        html_content=linebreaks(pitch.body, autoescape=True) if pitch.body else None,
    )
    # An anonymous pitch gets no automatic byline — the editor decides
    # whether and how to credit the person, and can add them by name on
    # the article's Authors screen (no account needed, see Author).
    if pitch.submitter:
        ArticleAuthor.objects.create(
            article=article, author=Author.for_user(pitch.submitter), order=0, is_corresponding=True,
        )
    return article
