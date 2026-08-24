from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView
from django_ratelimit.decorators import ratelimit

from articles.models import Article, ArticleAuthor
from users.decorators import role_required
from users.models import User

from .forms import PitchDecisionForm, StoryPitchForm
from .models import StoryPitch

# August 2026 decision: only verified_author accounts may pitch a story —
# same trust tier as byline authorship elsewhere on the site (see
# ROADMAP.md Phase 8). Not EDITORIAL_ROLES too — editorial staff write
# articles directly, they don't need to pitch themselves.
PITCH_SUBMIT_ROLES = (User.Role.VERIFIED_AUTHOR,)
# Reviewing pitches is editorial content triage, same boundary as Article
# CRUD — not the narrower EiC/Admin-only verification-queue boundary.
EDITORIAL_ROLES = User.EDITORIAL_ROLES


def _unique_article_slug(base):
    base = base or 'untitled-pitch'
    slug = base
    n = 2
    while Article.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


@method_decorator(role_required(*PITCH_SUBMIT_ROLES), name='dispatch')
@method_decorator(ratelimit(key='user', rate='10/h', method='POST', block=True), name='dispatch')
class PitchCreateView(CreateView):
    model = StoryPitch
    form_class = StoryPitchForm
    template_name = 'pitches/pitch_form.html'

    def form_valid(self, form):
        form.instance.submitter = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, 'Your pitch has been submitted — the editorial team will review it soon.')
        return response

    def get_success_url(self):
        return reverse('pitches:my_pitches')


@method_decorator(role_required(*PITCH_SUBMIT_ROLES), name='dispatch')
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
        if status:
            queryset = queryset.filter(status=status)
        else:
            queryset = queryset.exclude(status__in=[StoryPitch.Status.ACCEPTED, StoryPitch.Status.REJECTED, StoryPitch.Status.PUBLISHED])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = StoryPitch.Status.choices
        context['selected_status'] = self.request.GET.get('status', '')
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
        article = Article.objects.create(
            title=pitch.title, slug=_unique_article_slug(slugify(pitch.title)), abstract=pitch.summary,
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
            html_content=pitch.body or None,
        )
        ArticleAuthor.objects.create(article=article, user=pitch.submitter, order=0, is_corresponding=True)
        pitch.article = article
        pitch.status = StoryPitch.Status.ACCEPTED
        pitch.reviewed_by = request.user
        pitch.decided_at = timezone.now()
        pitch.save()
        messages.success(request, f'"{pitch.title}" accepted — draft article created, finish it up in Articles.')
        return redirect('articles:manage_article_update', slug=article.slug)

    return redirect('pitches:manage_pitch_detail', pk=pitch.pk)
