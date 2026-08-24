from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, ListView
from django_q.tasks import async_task

from users.decorators import role_required
from users.models import User

from .emails import send_confirmation_email
from .forms import NewsletterIssueForm, SubscribeForm
from .models import NewsletterIssue, Subscriber

EDITORIAL_ROLES = User.EDITORIAL_ROLES


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
    return redirect(request.POST.get('next') or 'articles:home')


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
        if status == 'sent':
            queryset = queryset.filter(sent_at__isnull=False)
        elif status == 'sending':
            queryset = queryset.filter(sent_at__isnull=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['confirmed_subscriber_count'] = Subscriber.objects.filter(
            status=Subscriber.Status.CONFIRMED,
        ).count()
        context['selected_status'] = self.request.GET.get('status', '')
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

        async_task('newsletter.tasks.send_newsletter_issue', self.object.pk)

        messages.success(
            self.request,
            f'"{self.object.subject}" is sending to '
            f'{Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED).count()} subscribers.',
        )
        return response

    def get_success_url(self):
        return reverse('newsletter:manage_issue_list')
