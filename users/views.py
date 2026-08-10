from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView
from django.views.generic.detail import DetailView

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
        user.verification_status = User.VerificationStatus.PENDING
        user.save(update_fields=['verification_status'])
        messages.success(request, 'Your verification request has been resubmitted.')
    return redirect('users:pending_verification')


@login_required
def verification_queue(request):
    if not (request.user.is_staff or request.user.role in (User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)):
        raise PermissionDenied

    pending_users = User.objects.filter(
        verification_status=User.VerificationStatus.PENDING,
    ).order_by('date_joined')
    return render(request, 'users/verification_queue.html', {'pending_users': pending_users})


@login_required
def verification_decide(request, pk, decision):
    if not (request.user.is_staff or request.user.role in (User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)):
        raise PermissionDenied
    if decision not in ('approve', 'reject') or request.method != 'POST':
        raise PermissionDenied

    target = get_object_or_404(User, pk=pk)
    if decision == 'approve':
        target.verification_status = User.VerificationStatus.APPROVED
        target.is_verified = True
        target.role = User.Role.VERIFIED_AUTHOR
        messages.success(request, f'{target.email} approved.')
    else:
        target.verification_status = User.VerificationStatus.REJECTED
        target.is_verified = False
        messages.success(request, f'{target.email} rejected.')
    target.save()
    return redirect('users:verification_queue')
