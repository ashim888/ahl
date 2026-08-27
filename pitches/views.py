from django.conf import settings
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

from articles.models import Article, ArticleAuthor
from users.decorators import role_required
from users.models import User

from .forms import PitchDecisionForm, StoryPitchForm
from .models import StoryPitch

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
        return context

    def form_valid(self, form):
        if self.request.user.is_authenticated:
            form.instance.submitter = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, 'Your pitch has been submitted — the editorial team will review it soon.')
        return response

    def get_success_url(self):
        # An anonymous submitter has no account to see pitches:my_pitches
        # with — the success message above is their only confirmation, so
        # send them back to the homepage where it'll actually render.
        if self.request.user.is_authenticated:
            return reverse('pitches:my_pitches')
        return reverse('articles:home')


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
        return context


@role_required(*EDITORIAL_ROLES)
def pitch_detail(request, pk):
    pitch = get_object_or_404(StoryPitch.objects.select_related('submitter', 'article'), pk=pk)
    if request.method == 'POST':
        form = PitchDecisionForm(request.POST, instance=pitch)
        if form.is_valid():
            form.save()
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
        # slug left blank — Article.save() generates one from the title
        # (plus a unique short_code) automatically.
        # pitch.body is plain text from a public, low-trust submission form
        # (any authenticated account, or anonymous — see StoryPitch's
        # docstring) — Article.html_content is documented as trusted,
        # editor-authored HTML rendered unescaped ({{ chunk|safe }} in
        # article_detail.html). linebreaks() escapes it into safe paragraph
        # HTML rather than pouring raw pitch text into that trust boundary,
        # which would otherwise let a pitch submitter's <script> execute for
        # the reviewing editor and, if published, every reader.
        article = Article.objects.create(
            title=pitch.title, abstract=pitch.summary,
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
            html_content=linebreaks(pitch.body, autoescape=True) if pitch.body else None,
        )
        # An anonymous pitch (no submitter account) can't get an automatic
        # byline — nobody to link. The editor adds authorship by hand (the
        # existing "Authors" screen on the article) once they've followed up
        # via pitch.contact_email, e.g. if that person registers an account.
        if pitch.submitter:
            ArticleAuthor.objects.create(article=article, user=pitch.submitter, order=0, is_corresponding=True)
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
            # See the matching comment in pitch_decide above — pitch.body is
            # low-trust public input, escaped via linebreaks() before it can
            # reach Article.html_content's "trusted HTML, rendered unescaped" field.
            article = Article.objects.create(
                title=pitch.title, abstract=pitch.summary,
                article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
                html_content=linebreaks(pitch.body, autoescape=True) if pitch.body else None,
            )
            if pitch.submitter:
                ArticleAuthor.objects.create(article=article, user=pitch.submitter, order=0, is_corresponding=True)
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
