from django.contrib import messages
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import EditorialBoardMemberForm
from .models import EditorialBoardMember

# Matches EDITORIAL_ROLES in articles/views.py and admin_custom/views.py —
# editorial board management is an Editor/EiC/Admin capability.
EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)


class EditorialBoardPublicView(ListView):
    """Public page — /about/editorial-board/."""

    model = EditorialBoardMember
    template_name = 'editorial_board/public_list.html'
    context_object_name = 'members'

    def get_queryset(self):
        return EditorialBoardMember.objects.filter(is_active=True)


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
