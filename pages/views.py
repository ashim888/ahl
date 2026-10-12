import re

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, UpdateView

from users.decorators import role_required
from users.models import User

from articles.seo import ld_json

from .forms import SitePageForm
from .models import SitePage


PAGE_DESCRIPTIONS = {
    'terms': _('The rules for reading, subscribing and taking part on Ajna Health Lens.'),
    'privacy': _('What personal data Ajna Health Lens collects, why, how long we keep it, and your rights.'),
    'refund-policy': _('How to cancel, and when and how we refund subscriptions, articles and courses.'),
    'faq': _('Answers about subscriptions, payments, free articles, organization access, pitching stories and your account.'),
}

_QUESTION_RE = re.compile(r'<h3[^>]*>(.*?)</h3>(.*?)(?=<h[23][\s>]|\Z)', re.S | re.I)


def faq_structured_data(body: str) -> str:
    """schema.org FAQPage JSON-LD from the FAQ body: each <h3> is a
    question, everything up to the next heading its answer."""
    questions = [
        {'@type': 'Question', 'name': strip_tags(question).strip(),
         'acceptedAnswer': {'@type': 'Answer', 'text': ' '.join(strip_tags(answer).split())}}
        for question, answer in _QUESTION_RE.findall(body or '')
    ]
    return ld_json({'@context': 'https://schema.org', '@type': 'FAQPage', 'mainEntity': questions}) if questions else ''


def page(request, slug):
    """/terms/, /privacy/, /refund-policy/ — senior staff can preview an
    unpublished page; everyone else gets a 404 until it's published."""
    site_page = get_object_or_404(SitePage, slug=slug)
    if not site_page.is_published and not (request.user.is_authenticated and request.user.is_senior_staff):
        raise Http404
    return render(request, 'pages/page.html', {
        'page': site_page,
        'meta_title': site_page.title,
        'meta_description': PAGE_DESCRIPTIONS.get(slug),
        'faq_json_ld': faq_structured_data(site_page.body) if slug == SitePage.Slug.FAQ else '',
    })


@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PageListView(ListView):
    model = SitePage
    template_name = 'pages/manage/page_list.html'
    context_object_name = 'pages'


@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PageUpdateView(UpdateView):
    model = SitePage
    form_class = SitePageForm
    template_name = 'pages/manage/page_form.html'
    slug_url_kwarg = 'slug'

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        form.save()
        state = 'published' if form.instance.is_published else 'saved as a draft (not public)'
        messages.success(self.request, f'"{form.instance.title_en}" {state}.')
        return redirect('pages:manage_page_list')
