"""Reader reports about articles and comments (ContentReport): the public
form at /report/?article=<id> or ?comment=<id>, the email to the editors,
and the editors' queue at /editorial/reports/."""
import logging

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView
from django_comments_xtd.models import XtdComment
from django_ratelimit.decorators import ratelimit

from ajna_health_lens.forms import apply_tailwind_widgets
from ajna_health_lens.mail import send_templated_email
from articles.models import Article
from users.decorators import role_required
from users.models import User

from .models import ContentReport

logger = logging.getLogger(__name__)


class ReportForm(forms.Form):
    reason = forms.ChoiceField(choices=ContentReport.Reason.choices, widget=forms.RadioSelect, label=_('What’s the problem?'))
    details = forms.CharField(
        label=_('Tell us more'), required=False, max_length=3000, widget=forms.Textarea(attrs={'rows': 5}),
        help_text=_('What’s wrong and where. For a copyright claim: which work is yours, where it was first published, '
                    'and confirm that you own it or act for the owner.'),
    )
    name = forms.CharField(label=_('Your name'), required=False, max_length=150)
    email = forms.EmailField(label=_('Your email'), required=False,
                             help_text=_('So we can tell you what we did. Required for copyright and privacy reports.'))
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user and user.is_authenticated:
            del self.fields['name']
            del self.fields['email']
        apply_tailwind_widgets(self, skip=('reason', 'website'))

    def clean(self):
        cleaned = super().clean()
        reason = cleaned.get('reason')
        if reason in (ContentReport.Reason.COPYRIGHT, ContentReport.Reason.PRIVACY, ContentReport.Reason.OTHER) \
                and not cleaned.get('details', '').strip():
            self.add_error('details', _('Please describe the problem so we can act on it.'))
        if reason in (ContentReport.Reason.COPYRIGHT, ContentReport.Reason.PRIVACY) and 'email' in self.fields \
                and not cleaned.get('email'):
            self.add_error('email', _('We need a way to reach you about this kind of report.'))
        return cleaned


def _target(request):
    """(article, comment, summary) from ?article= / ?comment=, or 404."""
    comment_id = request.GET.get('comment') or request.POST.get('comment')
    article_id = request.GET.get('article') or request.POST.get('article')
    if comment_id and str(comment_id).isdigit():
        comment = get_object_or_404(XtdComment, pk=comment_id, is_public=True, is_removed=False)
        article = comment.content_object if isinstance(comment.content_object, Article) else None
        return article, comment, f'Comment by {comment.name} on “{article.title if article else "an article"}”'[:300]
    if article_id and str(article_id).isdigit():
        article = get_object_or_404(Article, pk=article_id, status=Article.Status.PUBLISHED)
        return article, None, f'Article “{article.title}”'[:300]
    raise Http404


def _notify_editors(report):
    """Email the editors so a report is seen the same day."""
    recipients = set(User.objects.filter(
        role__in=User.SENIOR_STAFF_ROLES, is_active=True,
    ).values_list('email', flat=True))
    recipients.add(settings.JOURNAL_CONTACT_EMAIL)
    send_templated_email(
        subject=f'Report: {report.get_reason_display()} — {report.target_summary}'[:150],
        template='admin_custom/email/new_report',
        context={
            'report': report,
            'queue_url': f"{settings.SITE_BASE_URL}{reverse('admin_custom:manage_report_list')}",
            'target_url': f'{settings.SITE_BASE_URL}{report.target_url}' if report.target_url else '',
        },
        recipient_list=sorted(recipients),
    )


@ratelimit(key='ip', rate='8/h', method='POST', block=True)
def report_content(request):
    """/report/ — public; anyone can report, signed in or not."""
    article, comment, summary = _target(request)
    if request.method == 'POST':
        form = ReportForm(request.POST, user=request.user)
        if form.is_valid():
            if form.cleaned_data.get('website'):
                # Honeypot filled in: a bot. Pretend it worked.
                return render(request, 'admin_custom/report_thanks.html', {'article': article})
            user = request.user if request.user.is_authenticated else None
            report = ContentReport.objects.create(
                article=article, comment=comment, target_summary=summary,
                reason=form.cleaned_data['reason'], details=form.cleaned_data.get('details', '').strip(),
                reporter=user,
                reporter_name=user.get_full_name() if user else form.cleaned_data.get('name', ''),
                reporter_email=user.email if user else form.cleaned_data.get('email', ''),
            )
            _notify_editors(report)
            return render(request, 'admin_custom/report_thanks.html', {'article': article})
    else:
        form = ReportForm(user=request.user)
    return render(request, 'admin_custom/report_form.html', {
        'form': form, 'article': article, 'comment': comment, 'summary': summary,
    })


@method_decorator(role_required(*User.EDITORIAL_ROLES), name='dispatch')
class ReportListView(ListView):
    model = ContentReport
    template_name = 'admin_custom/manage/report_list.html'
    context_object_name = 'reports'
    paginate_by = 30

    def get_queryset(self):
        queryset = ContentReport.objects.select_related('article', 'comment', 'handled_by', 'reporter')
        status = self.request.GET.get('status', ContentReport.Status.OPEN)
        if status in ContentReport.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_status'] = self.request.GET.get('status', ContentReport.Status.OPEN)
        context['statuses'] = ContentReport.Status.choices
        return context


@role_required(*User.EDITORIAL_ROLES)
@require_POST
def report_handle(request, pk):
    """Close a report: 'resolve' (optionally hiding the reported comment)
    or 'dismiss'. The note is the record of what was done."""
    report = get_object_or_404(ContentReport, pk=pk)
    action = request.POST.get('action')
    if action not in ('resolve', 'dismiss', 'hide_comment', 'reopen'):
        raise Http404
    if action == 'reopen':
        report.status, report.handled_by, report.handled_at = ContentReport.Status.OPEN, None, None
        report.save(update_fields=['status', 'handled_by', 'handled_at'])
        messages.success(request, 'Report reopened.')
        return redirect(f"{reverse('admin_custom:manage_report_list')}?status=open")
    note = request.POST.get('note', '').strip()
    if action == 'hide_comment':
        if not report.comment_id:
            raise Http404
        XtdComment.objects.filter(pk=report.comment_id).order_by().update(is_removed=True)
        note = note or 'Comment removed.'
    report.status = ContentReport.Status.DISMISSED if action == 'dismiss' else ContentReport.Status.RESOLVED
    report.resolution_note = note
    report.handled_by = request.user
    report.handled_at = timezone.now()
    report.save(update_fields=['status', 'resolution_note', 'handled_by', 'handled_at'])
    logger.info('Report %s %s by %s: %s', report.pk, report.status, request.user.email, note)
    messages.success(request, f'Report marked “{report.get_status_display()}”.')
    return redirect('admin_custom:manage_report_list')
