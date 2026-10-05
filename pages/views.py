from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.generic import ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import SitePageForm
from .models import SitePage


def page(request, slug):
    """/terms/, /privacy/, /refund-policy/ — senior staff can preview an
    unpublished page; everyone else gets a 404 until it's published."""
    site_page = get_object_or_404(SitePage, slug=slug)
    if not site_page.is_published and not (request.user.is_authenticated and request.user.is_senior_staff):
        raise Http404
    return render(request, 'pages/page.html', {
        'page': site_page,
        'meta_title': site_page.title,
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
