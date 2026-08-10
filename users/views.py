from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView
from django.views.generic.detail import DetailView

from .decorators import role_required
from .forms import ProfileUpdateForm, RegistrationForm
from .models import User


class RegisterView(CreateView):
    model = User
    form_class = RegistrationForm
    template_name = 'users/register.html'
    success_url = reverse_lazy('users:pending_verification')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class EmailLoginView(LoginView):
    template_name = 'users/login.html'
    redirect_authenticated_user = True


class ProfileView(DetailView):
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'profile_user'

    def get_object(self, queryset=None):
        return self.request.user


class ProfileUpdateView(UpdateView):
    model = User
    form_class = ProfileUpdateForm
    template_name = 'users/profile_edit.html'
    success_url = reverse_lazy('users:profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, 'Profile updated.')
        return super().form_valid(form)


profile_view = login_required(ProfileView.as_view())
profile_update_view = login_required(ProfileUpdateView.as_view())


class PendingVerificationView(TemplateView):
    template_name = 'users/pending_verification.html'


pending_verification_view = login_required(PendingVerificationView.as_view())


@login_required
def reapply_verification(request):
    user = request.user
    if request.method == 'POST' and user.can_reapply:
        # Plain save() (no update_fields) so the pre_save signal's
        # verification_status_changed_at stamp is actually persisted.
        user.verification_status = User.VerificationStatus.PENDING
        user.save()
        messages.success(request, 'Your verification request has been resubmitted.')
    return redirect('users:pending_verification')


# Verifying users is an Editor-in-Chief/Admin capability (ARCHITECTURE.md §6.2) —
# deliberately not "is_staff", since Editors also have is_staff=True but aren't
# meant to approve/reject verifications themselves.
@role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)
def verification_queue(request):
    pending_users = User.objects.filter(
        verification_status=User.VerificationStatus.PENDING,
    ).order_by('date_joined')
    return render(request, 'users/verification_queue.html', {'pending_users': pending_users})


@role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)
def verification_decide(request, pk, decision):
    if decision not in ('approve', 'reject') or request.method != 'POST':
        raise PermissionDenied

    target = get_object_or_404(User, pk=pk)
    applied = target.approve_verification() if decision == 'approve' else target.reject_verification()
    if applied:
        messages.success(request, f'{target.email} {decision}d.')
    else:
        messages.error(
            request,
            f'{target.email} has role "{target.get_role_display()}", which the verification '
            'queue does not manage — no change made.',
        )
    return redirect('users:verification_queue')
