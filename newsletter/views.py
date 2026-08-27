from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView
from django_q.models import Task
from django_q.tasks import async_task
from django_ratelimit.decorators import ratelimit

from users.decorators import role_required
from users.models import User

from .emails import send_confirmation_email
from .forms import NewsletterIssueForm, SubscribeForm
from .models import NewsletterIssue, Subscriber

# Placeholder shown in the preview instead of a real subscriber's one-click
# link — send_newsletter_issue (tasks.py) builds the real, token-based URL
# per recipient, which doesn't exist until an actual send happens.
PREVIEW_UNSUBSCRIBE_URL = '#preview-unsubscribe-link-not-real'

EDITORIAL_ROLES = User.EDITORIAL_ROLES


@ratelimit(key='ip', rate='10/h', method='POST', block=True)
def subscribe(request):
    """POST target for both the footer and inline signup forms (base.html /
    article_detail.html) — redirects back wherever the visitor came from.
    """
    if request.method == 'POST':
        form = SubscribeForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = request.user if request.user.is_authenticated else None
            subscriber, created = Subscriber.objects.get_or_create(
                email=email, defaults={'user': user},
            )
            if subscriber.status == Subscriber.Status.CONFIRMED:
                messages.info(request, "You're already subscribed.")
            else:
                if not created and subscriber.status == Subscriber.Status.UNSUBSCRIBED:
                    subscriber.status = Subscriber.Status.PENDING
                    subscriber.save(update_fields=['status'])
                send_confirmation_email(subscriber)
                messages.success(request, 'Check your email to confirm your subscription.')
        elif form.errors.get('website'):
            # Honeypot tripped — pretend it worked, don't tell the bot why.
            messages.success(request, 'Check your email to confirm your subscription.')
        else:
            messages.error(request, 'Enter a valid email address.')
    # `next` is attacker-controllable POST data on a public, unauthenticated
    # endpoint — url_has_allowed_host_and_scheme rejects an absolute/external
    # URL (open-redirect guard) rather than trusting it just because it was present.
    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('articles:home')


def confirm(request, token):
    subscriber = get_object_or_404(Subscriber, confirm_token=token)
    if subscriber.status == Subscriber.Status.PENDING:
        subscriber.status = Subscriber.Status.CONFIRMED
        subscriber.confirmed_at = timezone.now()
        subscriber.save(update_fields=['status', 'confirmed_at'])
    return render(request, 'newsletter/confirmed.html', {'subscriber': subscriber})


def unsubscribe(request, token):
    subscriber = get_object_or_404(Subscriber, unsubscribe_token=token)
    if subscriber.status != Subscriber.Status.UNSUBSCRIBED:
        subscriber.status = Subscriber.Status.UNSUBSCRIBED
        subscriber.unsubscribed_at = timezone.now()
        subscriber.save(update_fields=['status', 'unsubscribed_at'])
    return render(request, 'newsletter/unsubscribed.html', {'subscriber': subscriber})


# -- Editorial — compose & send (admin_custom-style dashboard pages) -------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class IssueListView(ListView):
    model = NewsletterIssue
    template_name = 'newsletter/manage/issue_list.html'
    context_object_name = 'issues'
    paginate_by = 30

    def get_queryset(self):
        queryset = NewsletterIssue.objects.order_by('-created_at')
        status = self.request.GET.get('status')
        q = self.request.GET.get('q')
        failed_task_ids = Task.objects.filter(success=False).values_list('id', flat=True)
        if status == 'sent':
            queryset = queryset.filter(sent_at__isnull=False)
        elif status == 'failed':
            queryset = queryset.filter(sent_at__isnull=True, task_id__in=failed_task_ids)
        elif status == 'sending':
            queryset = queryset.filter(sent_at__isnull=True).exclude(task_id__in=failed_task_ids)
        if q:
            queryset = queryset.filter(subject__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['confirmed_subscriber_count'] = Subscriber.objects.filter(
            status=Subscriber.Status.CONFIRMED,
        ).count()
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_q'] = self.request.GET.get('q', '')
        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class IssueComposeView(CreateView):
    model = NewsletterIssue
    form_class = NewsletterIssueForm
    template_name = 'newsletter/manage/issue_compose.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['confirmed_subscriber_count'] = Subscriber.objects.filter(
            status=Subscriber.Status.CONFIRMED,
        ).count()
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)

        task_id = async_task('newsletter.tasks.send_newsletter_issue', self.object.pk)
        self.object.task_id = task_id
        self.object.save(update_fields=['task_id'])

        messages.success(
            self.request,
            f'"{self.object.subject}" is sending to '
            f'{Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED).count()} subscribers.',
        )
        return response

    def get_success_url(self):
        return reverse('newsletter:manage_issue_list')


@role_required(*EDITORIAL_ROLES)
@require_POST
def issue_preview(request):
    """Renders in-progress compose-form data the way send_newsletter_issue
    (tasks.py) actually builds the email — subject + body_html + an
    unsubscribe footer — without saving anything or sending anything.
    Opened in a new tab from issue_compose.html, same pattern as
    articles:manage_article_preview.
    """
    form = NewsletterIssueForm(request.POST)
    if not form.is_valid():
        return render(request, 'newsletter/manage/issue_preview_error.html', {'form': form}, status=400)

    return render(request, 'newsletter/manage/issue_preview.html', {
        'subject': form.cleaned_data['subject'],
        'body_html': form.cleaned_data['body_html'],
        'unsubscribe_url': PREVIEW_UNSUBSCRIBE_URL,
    })


@role_required(*EDITORIAL_ROLES)
@require_POST
def issue_retry(request, pk):
    """Re-enqueues a failed send — the original task's failure is left in
    django_q's own Task table as history; this just points the issue at a
    fresh attempt.
    """
    issue = get_object_or_404(NewsletterIssue, pk=pk)
    if issue.get_send_status() != NewsletterIssue.Status.FAILED:
        messages.error(request, 'This issue is not in a failed state.')
        return redirect('newsletter:manage_issue_list')

    task_id = async_task('newsletter.tasks.send_newsletter_issue', issue.pk)
    issue.task_id = task_id
    issue.save(update_fields=['task_id'])
    messages.success(request, f'Retrying "{issue.subject}".')
    return redirect('newsletter:manage_issue_list')
