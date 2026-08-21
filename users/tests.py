from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

# django_ratelimit buckets requests into a fixed time window (see
# django_ratelimit.core._get_window) — a slow burst of requests risks
# flakily straddling a window reset if it happens to run near a boundary.
# Django's real password hasher (PBKDF2) is deliberately slow, so a 15+
# request login/register burst could take long enough for that to matter;
# swapping in a fast test-only hasher (Django's own documented pattern for
# exactly this) keeps the whole burst well under a second, not a fix for
# time itself. (freeze_time was tried and rejected — it hung the test
# runner, apparently confusing the MySQL driver's connection handling.)
FAST_PASSWORD_HASHERS = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


@FAST_PASSWORD_HASHERS
class LoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_normal_login_attempts_are_not_blocked(self):
        for _ in range(3):
            response = self.client.post(reverse('users:login'), {'username': 'nobody@example.com', 'password': 'wrong'})
            self.assertEqual(response.status_code, 200)  # re-renders the form with an error, not blocked

    def test_excessive_login_attempts_are_rate_limited(self):
        # Limit is 15/m (users/views.py EmailLoginView) — the 16th POST in
        # the same window should be blocked rather than processed.
        for _ in range(15):
            self.client.post(reverse('users:login'), {'username': 'nobody@example.com', 'password': 'wrong'})
        response = self.client.post(reverse('users:login'), {'username': 'nobody@example.com', 'password': 'wrong'})
        self.assertEqual(response.status_code, 403)


@FAST_PASSWORD_HASHERS
class RegisterRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_excessive_registration_attempts_are_rate_limited(self):
        # Limit is 10/h (users/views.py RegisterView).
        for i in range(10):
            self.client.post(reverse('users:register'), {'email': f'spam{i}@example.com'})
        response = self.client.post(reverse('users:register'), {'email': 'spam-overflow@example.com'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email='spam-overflow@example.com').exists())


def make_user(email, role, **extra):
    return User.objects.create_user(email=email, password='pw', first_name='F', last_name='L', role=role, **extra)


@FAST_PASSWORD_HASHERS
class VerificationQueueAccessTests(TestCase):
    """EiC/Admin only — deliberately narrower than EDITORIAL_ROLES, since a
    plain Editor is editorial staff but not meant to decide verifications
    (ARCHITECTURE.md §6.3).
    """

    def setUp(self):
        self.eic = make_user('eic@example.com', User.Role.EDITOR_IN_CHIEF)
        self.editor = make_user('editor@example.com', User.Role.EDITOR)
        self.pending = make_user(
            'pending@example.com', User.Role.UNVERIFIED, verification_status=User.VerificationStatus.PENDING,
        )

    def test_eic_can_view_queue(self):
        self.client.force_login(self.eic)
        response = self.client.get(reverse('users:verification_queue'))
        self.assertEqual(response.status_code, 200)

    def test_plain_editor_cannot_view_queue(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('users:verification_queue'))
        self.assertEqual(response.status_code, 403)

    def test_approve_verifies_user(self):
        self.client.force_login(self.eic)
        self.client.post(reverse('users:verification_decide', args=[self.pending.pk, 'approve']))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.role, User.Role.VERIFIED_AUTHOR)
        self.assertTrue(self.pending.is_verified)

    def test_reject_does_not_verify_user(self):
        self.client.force_login(self.eic)
        self.client.post(reverse('users:verification_decide', args=[self.pending.pk, 'reject']))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.verification_status, User.VerificationStatus.REJECTED)

    def test_invalid_decision_rejected(self):
        self.client.force_login(self.eic)
        response = self.client.post(reverse('users:verification_decide', args=[self.pending.pk, 'maybe']))
        self.assertEqual(response.status_code, 403)

    def test_plain_editor_cannot_decide(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('users:verification_decide', args=[self.pending.pk, 'approve']))
        self.assertEqual(response.status_code, 403)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.role, User.Role.UNVERIFIED)


@FAST_PASSWORD_HASHERS
class AuthorManagementAccessTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor2@example.com', User.Role.EDITOR)
        self.author = make_user('author2@example.com', User.Role.VERIFIED_AUTHOR)

    def test_editor_can_list_authors(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('users:manage_author_list'))
        self.assertEqual(response.status_code, 200)

    def test_verified_author_cannot_manage_authors(self):
        self.client.force_login(self.author)
        response = self.client.get(reverse('users:manage_author_list'))
        self.assertEqual(response.status_code, 403)

    def test_editor_can_toggle_author_active(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('users:manage_author_toggle_active', args=[self.author.pk]))
        self.author.refresh_from_db()
        self.assertFalse(self.author.is_active)


@FAST_PASSWORD_HASHERS
class StaffManagementAccessTests(TestCase):
    """EiC/Admin only — a plain Editor must NOT be able to manage other
    staff accounts, even though Editor is editorial staff.
    """

    def setUp(self):
        self.admin = make_user('admin2@example.com', User.Role.ADMIN, is_staff=True, is_superuser=True)
        self.eic = make_user('eic2@example.com', User.Role.EDITOR_IN_CHIEF)
        self.editor = make_user('editor3@example.com', User.Role.EDITOR)

    def test_eic_can_list_staff(self):
        self.client.force_login(self.eic)
        response = self.client.get(reverse('users:manage_staff_list'))
        self.assertEqual(response.status_code, 200)

    def test_plain_editor_cannot_manage_staff(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('users:manage_staff_list'))
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_deactivate_own_account(self):
        self.client.force_login(self.eic)
        self.client.post(reverse('users:manage_staff_toggle_active', args=[self.eic.pk]))
        self.eic.refresh_from_db()
        self.assertTrue(self.eic.is_active)

    def test_eic_can_deactivate_other_staff(self):
        self.client.force_login(self.eic)
        self.client.post(reverse('users:manage_staff_toggle_active', args=[self.editor.pk]))
        self.editor.refresh_from_db()
        self.assertFalse(self.editor.is_active)

    def test_eic_cannot_grant_admin_role_via_staff_form(self):
        self.client.force_login(self.eic)
        response = self.client.post(reverse('users:manage_staff_update', args=[self.editor.pk]), {
            'first_name': self.editor.first_name, 'last_name': self.editor.last_name,
            'email': self.editor.email, 'role': User.Role.ADMIN, 'is_active': 'on',
        })
        self.editor.refresh_from_db()
        self.assertNotEqual(self.editor.role, User.Role.ADMIN)
        self.assertEqual(response.status_code, 200)  # re-rendered with a form error, not a redirect

    def test_admin_can_grant_admin_role_via_staff_form(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('users:manage_staff_update', args=[self.editor.pk]), {
            'first_name': self.editor.first_name, 'last_name': self.editor.last_name,
            'email': self.editor.email, 'role': User.Role.ADMIN, 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.role, User.Role.ADMIN)


@FAST_PASSWORD_HASHERS
class ChangeRoleTests(TestCase):
    """The one screen that can move a user across the whole Role enum —
    users/views.py:change_role. Same Admin-grant guardrail as staff
    management, plus a self-change block.
    """

    def setUp(self):
        self.admin = make_user('admin3@example.com', User.Role.ADMIN, is_staff=True, is_superuser=True)
        self.eic = make_user('eic3@example.com', User.Role.EDITOR_IN_CHIEF)
        self.author = make_user('author3@example.com', User.Role.VERIFIED_AUTHOR)

    def test_eic_can_promote_author_to_editor(self):
        self.client.force_login(self.eic)
        response = self.client.post(reverse('users:change_role', args=[self.author.pk]), {'role': User.Role.EDITOR})
        self.assertEqual(response.status_code, 302)
        self.author.refresh_from_db()
        self.assertEqual(self.author.role, User.Role.EDITOR)

    def test_eic_cannot_grant_admin_via_change_role(self):
        self.client.force_login(self.eic)
        response = self.client.post(reverse('users:change_role', args=[self.author.pk]), {'role': User.Role.ADMIN})
        self.author.refresh_from_db()
        self.assertNotEqual(self.author.role, User.Role.ADMIN)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_grant_admin_via_change_role(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('users:change_role', args=[self.author.pk]), {'role': User.Role.ADMIN})
        self.assertEqual(response.status_code, 302)
        self.author.refresh_from_db()
        self.assertEqual(self.author.role, User.Role.ADMIN)

    def test_cannot_change_own_role(self):
        self.client.force_login(self.eic)
        response = self.client.post(reverse('users:change_role', args=[self.eic.pk]), {'role': User.Role.EDITOR})
        self.assertEqual(response.status_code, 302)
        self.eic.refresh_from_db()
        self.assertEqual(self.eic.role, User.Role.EDITOR_IN_CHIEF)

    def test_verified_author_cannot_access_change_role(self):
        self.client.force_login(self.author)
        response = self.client.get(reverse('users:change_role', args=[self.eic.pk]))
        self.assertEqual(response.status_code, 403)


@FAST_PASSWORD_HASHERS
class GroupManagementAccessTests(TestCase):
    """Admin-only — deliberately narrower than STAFF_MANAGE_ROLES; an EiC
    manages staff/roles but not raw Django Group/Permission config.
    """

    def setUp(self):
        self.admin = make_user('admin4@example.com', User.Role.ADMIN, is_staff=True, is_superuser=True)
        self.eic = make_user('eic4@example.com', User.Role.EDITOR_IN_CHIEF)

    def test_admin_can_list_groups(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:manage_group_list'))
        self.assertEqual(response.status_code, 200)

    def test_eic_cannot_access_group_management(self):
        self.client.force_login(self.eic)
        response = self.client.get(reverse('users:manage_group_list'))
        self.assertEqual(response.status_code, 403)

    def test_eic_cannot_manage_user_groups(self):
        target = make_user('target@example.com', User.Role.EDITOR)
        self.client.force_login(self.eic)
        response = self.client.get(reverse('users:manage_user_groups', args=[target.pk]))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_group(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('users:manage_group_create'), {'name': 'Reviewers', 'permissions': []})
        self.assertEqual(response.status_code, 302)
        from django.contrib.auth.models import Group
        self.assertTrue(Group.objects.filter(name='Reviewers').exists())
