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
        # Limit is 15/m by IP (users/views.py EmailLoginView) — the 16th POST
        # in the same window should be blocked rather than processed. Uses a
        # distinct username per attempt so django-axes' account-level lockout
        # (AXES_FAILURE_LIMIT=5, see AccountLockoutTests below) never kicks
        # in and this test stays isolated to exercising django_ratelimit only.
        for i in range(15):
            self.client.post(reverse('users:login'), {'username': f'nobody{i}@example.com', 'password': 'wrong'})
        response = self.client.post(reverse('users:login'), {'username': 'nobody-overflow@example.com', 'password': 'wrong'})
        self.assertEqual(response.status_code, 403)


@FAST_PASSWORD_HASHERS
class AccountLockoutTests(TestCase):
    """django-axes account-level lockout (settings.py AUTHENTICATION_BACKENDS/
    AXES_*) — locks by username (email), independent of source IP, so it
    still stops an attacker who rotates IPs against one account. Deliberately
    a separate concern from LoginRateLimitTests above, which covers the
    per-IP throttle.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='locktarget@example.com', password='correct-horse', first_name='F', last_name='L',
        )

    def test_locks_out_after_failure_limit_regardless_of_correct_password(self):
        # AXES_FAILURE_LIMIT=5 — the 6th attempt (even with the right
        # password) should be blocked rather than logged in.
        for _ in range(5):
            self.client.post(reverse('users:login'), {'username': self.user.email, 'password': 'wrong'})
        response = self.client.post(reverse('users:login'), {'username': self.user.email, 'password': 'correct-horse'})
        self.assertEqual(response.status_code, 429)

    def test_failures_on_one_account_do_not_lock_out_another(self):
        other = User.objects.create_user(
            email='other@example.com', password='correct-horse', first_name='O', last_name='T',
        )
        for _ in range(5):
            self.client.post(reverse('users:login'), {'username': self.user.email, 'password': 'wrong'})
        response = self.client.post(reverse('users:login'), {'username': other.email, 'password': 'correct-horse'})
        self.assertEqual(response.status_code, 302)


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


@FAST_PASSWORD_HASHERS
class RegisterSuccessTests(TestCase):
    """A *valid* submission — RegisterRateLimitTests above deliberately posts
    incomplete data, which never reaches form_valid()/login(), so it can't
    catch a regression there (see the "multiple authentication backends"
    login() bug this class exists to guard against).
    """

    def test_valid_registration_creates_and_logs_in_user(self):
        response = self.client.post(reverse('users:register'), {
            'email': 'newauthor@example.com', 'first_name': 'New', 'last_name': 'Author',
            'password1': 'a-strong-passw0rd!', 'password2': 'a-strong-passw0rd!',
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email='newauthor@example.com')
        self.assertEqual(user.role, User.Role.UNVERIFIED)
        self.assertEqual(user.verification_status, User.VerificationStatus.PENDING)
        # Registration logs the new account straight in — confirmed by
        # requesting a login-required page and never being bounced to /login/.
        profile_response = self.client.get(reverse('users:profile'))
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.context['profile_user'], user)


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

    def test_groups_list_newest_first(self):
        from django.contrib.auth.models import Group
        first = Group.objects.create(name='Older Group')
        second = Group.objects.create(name='Newer Group')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:manage_group_list'))
        groups = list(response.context['groups'])
        self.assertLess(groups.index(second), groups.index(first))


@FAST_PASSWORD_HASHERS
class ManageListOrderingTests(TestCase):
    """"Last entered item at the top" — listing pages default to newest-
    first rather than alphabetical/role grouping (still available via the
    Role filter on these two screens).
    """

    def setUp(self):
        self.admin = make_user('order-admin@example.com', User.Role.ADMIN, is_staff=True, is_superuser=True)

    def test_staff_list_newest_first(self):
        older = make_user('older-staff@example.com', User.Role.EDITOR)
        newer = make_user('newer-staff@example.com', User.Role.EDITOR)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:manage_staff_list'))
        staff = list(response.context['staff'])
        self.assertLess(staff.index(newer), staff.index(older))

    def test_permissions_list_newest_first(self):
        older = make_user('older-account@example.com', User.Role.VERIFIED_AUTHOR)
        newer = make_user('newer-account@example.com', User.Role.VERIFIED_AUTHOR)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:manage_permissions_list'))
        accounts = list(response.context['accounts'])
        self.assertLess(accounts.index(newer), accounts.index(older))


@FAST_PASSWORD_HASHERS
class ProfileViewPitchesTests(TestCase):
    """The profile page previously showed Training Enrollments but nothing
    about story pitches at all — no section, no link in — even though
    pitches/models.py:StoryPitch has existed since Phase 8.
    """

    def test_story_pitches_section_shown_for_verified_author(self):
        from pitches.models import StoryPitch

        author = make_user('profile-pitch-author@example.com', User.Role.VERIFIED_AUTHOR)
        StoryPitch.objects.create(title='My Great Idea', summary='s', submitter=author)
        self.client.force_login(author)
        response = self.client.get(reverse('users:profile'))
        self.assertContains(response, 'STORY PITCHES')
        self.assertContains(response, 'My Great Idea')
        self.assertEqual(list(response.context['story_pitches']), list(StoryPitch.objects.filter(submitter=author)))

    def test_story_pitches_section_shown_for_unverified_reader_too(self):
        # Any authenticated account, not just already-verified authors — see
        # pitches.views.PitchCreateView.
        reader = make_user('profile-pitch-unverified@example.com', User.Role.UNVERIFIED)
        self.client.force_login(reader)
        response = self.client.get(reverse('users:profile'))
        self.assertContains(response, 'STORY PITCHES')

    def test_story_pitches_section_shown_for_editorial_staff_too(self):
        # No role restriction at all now — the profile page itself is
        # login_required, so any account that can view it can pitch.
        editor = make_user('profile-pitch-editor@example.com', User.Role.EDITOR)
        self.client.force_login(editor)
        response = self.client.get(reverse('users:profile'))
        self.assertContains(response, 'STORY PITCHES')
