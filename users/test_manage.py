"""Account and staff management beyond users/tests.py: the user manager,
access decorators, upload validators, admin actions, the verification
screens' edge cases, account/staff creation, role changes and groups."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .decorators import role_required, verification_required
from .models import User
from .tests import FAST_PASSWORD_HASHERS, make_user
from .validators import validate_cv_file_size, validate_photo_size


class UserManagerTests(TestCase):
    def test_email_is_required_and_normalised(self):
        with self.assertRaisesMessage(ValueError, 'Users must have an email address'):
            User.objects.create_user(email='', password='pw')
        user = User.objects.create_user(email='Someone@EXAMPLE.com', password='pw', first_name='S', last_name='O')
        self.assertEqual(user.email, 'Someone@example.com')
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_superuser_is_an_approved_admin(self):
        user = User.objects.create_superuser(email='root@example.com', password='pw', first_name='R', last_name='T')
        self.assertTrue(user.is_superuser and user.is_staff and user.is_verified)
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertEqual(user.verification_status, User.VerificationStatus.APPROVED)

    def test_superuser_flags_cannot_be_switched_off(self):
        with self.assertRaisesMessage(ValueError, 'is_staff=True'):
            User.objects.create_superuser(email='a@example.com', password='pw', is_staff=False)
        with self.assertRaisesMessage(ValueError, 'is_superuser=True'):
            User.objects.create_superuser(email='b@example.com', password='pw', is_superuser=False)

    def test_inactive_editor_cannot_publish(self):
        eic = make_user('inactive-eic@example.com', User.Role.EDITOR_IN_CHIEF, is_active=False)
        self.assertFalse(eic.can_publish)


class DecoratorTests(TestCase):
    """users/decorators.py on a bare view."""

    def setUp(self):
        self.factory = RequestFactory()

        def view(request):
            return HttpResponse('ok')

        self.verified_view = verification_required(view)
        self.editor_view = role_required(User.Role.EDITOR)(view)

    def _request(self, user):
        request = self.factory.get('/somewhere/')
        request.user = user
        return request

    def test_verification_required(self):
        anonymous = self.verified_view(self._request(AnonymousUser()))
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn(reverse('users:login'), anonymous.url)
        unverified = self.verified_view(self._request(make_user('unv@example.com', User.Role.UNVERIFIED)))
        self.assertEqual(unverified.url, reverse('users:pending_verification'))
        verified = self.verified_view(self._request(make_user('ver@example.com', User.Role.VERIFIED_AUTHOR)))
        self.assertEqual(verified.content, b'ok')

    def test_role_required(self):
        self.assertEqual(self.editor_view(self._request(make_user('ed@example.com', User.Role.EDITOR))).content, b'ok')
        with self.assertRaises(PermissionDenied):
            self.editor_view(self._request(make_user('au@example.com', User.Role.VERIFIED_AUTHOR)))
        # A superuser passes whatever their role field says.
        superuser = make_user('su@example.com', User.Role.UNVERIFIED, is_superuser=True)
        self.assertEqual(self.editor_view(self._request(superuser)).content, b'ok')


@override_settings(CV_MAX_UPLOAD_SIZE_MB=1, PROFILE_PHOTO_MAX_UPLOAD_SIZE_MB=1)
class UploadSizeValidatorTests(TestCase):
    def test_limits(self):
        one_mb = 1024 * 1024
        validate_cv_file_size(SimpleNamespace(size=one_mb))
        validate_photo_size(SimpleNamespace(size=one_mb))
        with self.assertRaisesMessage(ValidationError, 'CV file must be under 1 MB.'):
            validate_cv_file_size(SimpleNamespace(size=one_mb + 1))
        with self.assertRaisesMessage(ValidationError, 'Photo must be under 1 MB.'):
            validate_photo_size(SimpleNamespace(size=one_mb + 1))

    def test_the_other_apps_size_validators(self):
        from articles.validators import validate_article_pdf_size, validate_featured_image_size
        from editorial_board.validators import validate_photo_size as board_photo
        from issues.validators import validate_cover_image_size

        with self.settings(ARTICLE_PDF_MAX_UPLOAD_SIZE_MB=1, ARTICLE_IMAGE_MAX_UPLOAD_SIZE_MB=1, ISSUE_COVER_MAX_UPLOAD_SIZE_MB=1):
            for validator in (validate_article_pdf_size, validate_featured_image_size, board_photo, validate_cover_image_size):
                validator(SimpleNamespace(size=1024))
                with self.assertRaises(ValidationError, msg=validator.__name__):
                    validator(SimpleNamespace(size=2 * 1024 * 1024))


@FAST_PASSWORD_HASHERS
class AdminActionTests(TestCase):
    """The approve/reject bulk actions in Django's /admin/."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(email='admin-actions@example.com', password='pw', first_name='A', last_name='D')
        self.pending = make_user('pending-admin@example.com', User.Role.UNVERIFIED, verification_status=User.VerificationStatus.PENDING)
        self.editor = make_user('editor-admin@example.com', User.Role.EDITOR)
        self.client.force_login(self.superuser)

    def _action(self, action):
        return self.client.post(reverse('admin:users_user_changelist'), {
            'action': action, '_selected_action': [self.pending.pk, self.editor.pk],
        }, follow=True)

    def test_approve_skips_staff(self):
        response = self._action('approve_verification')
        self.assertContains(response, '1 user(s) approved. 1 skipped')
        self.pending.refresh_from_db()
        self.editor.refresh_from_db()
        self.assertEqual(self.pending.role, User.Role.VERIFIED_AUTHOR)
        self.assertEqual(self.editor.role, User.Role.EDITOR)

    def test_reject_skips_staff(self):
        response = self._action('reject_verification')
        self.assertContains(response, '1 user(s) rejected. 1 skipped')
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.verification_status, User.VerificationStatus.REJECTED)


@FAST_PASSWORD_HASHERS
class VerificationScreenEdgeTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-verify@example.com', User.Role.EDITOR_IN_CHIEF)
        self.pending = make_user(
            'pending-verify@example.com', User.Role.UNVERIFIED, verification_status=User.VerificationStatus.PENDING,
            bio='Public health researcher in Jumla.',
        )
        self.client.force_login(self.eic)

    def test_detail_shows_a_pending_registration_only(self):
        response = self.client.get(reverse('users:verification_detail', args=[self.pending.pk]))
        self.assertContains(response, 'Public health researcher in Jumla.')
        approved = make_user('approved-verify@example.com', User.Role.VERIFIED_AUTHOR,
                             verification_status=User.VerificationStatus.APPROVED)
        self.assertEqual(self.client.get(reverse('users:verification_detail', args=[approved.pk])).status_code, 404)

    def test_decide_needs_post_and_a_known_decision(self):
        approve = reverse('users:verification_decide', args=[self.pending.pk, 'approve'])
        self.assertEqual(self.client.get(approve).status_code, 403)
        self.assertEqual(self.client.post(reverse('users:verification_decide', args=[self.pending.pk, 'promote'])).status_code, 403)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.role, User.Role.UNVERIFIED)

    def test_deciding_on_staff_is_refused_with_a_message(self):
        editor = make_user('editor-verify@example.com', User.Role.EDITOR)
        response = self.client.post(reverse('users:verification_decide', args=[editor.pk, 'reject']), follow=True)
        self.assertContains(response, 'which the verification')
        editor.refresh_from_db()
        self.assertEqual(editor.role, User.Role.EDITOR)

    def test_bulk_with_nothing_eligible(self):
        editor = make_user('editor-bulk@example.com', User.Role.EDITOR)
        response = self.client.post(reverse('users:verification_bulk_decide'), {
            'decision': 'approve', 'pks': [editor.pk],
        }, follow=True)
        self.assertContains(response, 'No eligible users were selected.')
        self.assertEqual(self.client.post(reverse('users:verification_bulk_decide'), {'decision': 'delete'}).status_code, 403)


@FAST_PASSWORD_HASHERS
class AccountManagementEdgeTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor-accounts@example.com', User.Role.EDITOR)
        self.client.force_login(self.editor)

    def _create(self, **overrides):
        data = {
            'first_name': 'Sita', 'last_name': 'Rai', 'email': 'sita.rai@example.com',
            'role': User.Role.VERIFIED_AUTHOR, 'password1': '', 'password2': '',
        }
        data.update(overrides)
        return self.client.post(reverse('users:manage_account_create'), data)

    def test_list_filters_by_role_and_search(self):
        make_user('reader-list@example.com', User.Role.UNVERIFIED, affiliation='Dhulikhel Hospital')
        author = make_user('author-list@example.com', User.Role.VERIFIED_AUTHOR)
        url = reverse('users:manage_account_list')
        by_role = self.client.get(url, {'role': User.Role.VERIFIED_AUTHOR}).context['accounts']
        self.assertEqual(list(by_role), [author])
        by_search = self.client.get(url, {'q': 'dhulikhel'}).context['accounts']
        self.assertEqual([u.email for u in by_search], ['reader-list@example.com'])

    def test_mismatched_passwords_are_rejected(self):
        response = self._create(password1='Kathmandu-2026!', password2='Kathmandu-2027!')
        self.assertFormError(response.context['form'], 'password2', "The two passwords don't match.")
        self.assertFalse(User.objects.filter(email='sita.rai@example.com').exists())

    def test_weak_password_is_rejected(self):
        response = self._create(password1='123', password2='123')
        self.assertTrue(response.context['form'].errors.get('password1'))
        self.assertFalse(User.objects.filter(email='sita.rai@example.com').exists())

    def test_password_given_means_no_invite(self):
        with patch('users.views.send_account_invite') as invite:
            self._create(password1='Kathmandu-2026!', password2='Kathmandu-2026!')
        invite.assert_not_called()
        self.assertTrue(User.objects.get(email='sita.rai@example.com').check_password('Kathmandu-2026!'))

    def test_failed_invite_still_creates_the_account_and_warns(self):
        with patch('users.views.send_account_invite', return_value=False):
            response = self._create()
        user = User.objects.get(email='sita.rai@example.com')
        self.assertFalse(user.has_usable_password())
        self.assertEqual(response.status_code, 302)
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any('could not be sent' in m for m in messages))

    def test_author_who_already_has_an_account_is_not_given_another(self):
        from articles.models import Author

        existing = make_user('linked@example.com', User.Role.VERIFIED_AUTHOR)
        author = Author.objects.create(name='Linked Author', user=existing)
        response = self.client.get(reverse('users:manage_account_create'), {'author': author.pk})
        self.assertRedirects(response, reverse('articles:manage_author_update', args=[author.pk]), fetch_redirect_response=False)

    def test_resend_invite(self):
        invited = make_user('invited@example.com', User.Role.VERIFIED_AUTHOR)
        invited.set_unusable_password()
        invited.save()
        url = reverse('users:manage_account_resend_invite', args=[invited.pk])
        with patch('users.views.send_account_invite', return_value=True) as invite:
            response = self.client.post(url, follow=True)
        invite.assert_called_once()
        self.assertContains(response, 'Invitation re-sent to invited@example.com.')
        with patch('users.views.send_account_invite', return_value=False):
            self.assertContains(self.client.post(url, follow=True), 'could not be sent')

    def test_no_invite_for_someone_who_set_a_password(self):
        active = make_user('active@example.com', User.Role.VERIFIED_AUTHOR)
        with patch('users.views.send_account_invite') as invite:
            response = self.client.post(reverse('users:manage_account_resend_invite', args=[active.pk]), follow=True)
        invite.assert_not_called()
        self.assertContains(response, 'has already set a password.')

    def test_resend_invite_cannot_target_staff(self):
        eic = make_user('eic-invite@example.com', User.Role.EDITOR_IN_CHIEF)
        self.assertEqual(self.client.post(reverse('users:manage_account_resend_invite', args=[eic.pk])).status_code, 404)


@FAST_PASSWORD_HASHERS
class StaffAndRoleTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-staff@example.com', User.Role.EDITOR_IN_CHIEF)
        self.client.force_login(self.eic)

    def _new_staff(self, **overrides):
        data = {
            'first_name': 'Ram', 'last_name': 'Thapa', 'email': 'ram.thapa@example.com', 'role': User.Role.EDITOR,
            'is_active': 'on', 'password1': 'Kathmandu-2026!', 'password2': 'Kathmandu-2026!',
        }
        data.update(overrides)
        return self.client.post(reverse('users:manage_staff_create'), data)

    def test_eic_adds_an_editor_who_can_publish(self):
        page = self.client.get(reverse('users:manage_staff_create'))
        self.assertTrue(page.context['is_create'])
        response = self._new_staff(can_publish='on')
        self.assertRedirects(response, reverse('users:manage_staff_list'), fetch_redirect_response=False)
        editor = User.objects.get(email='ram.thapa@example.com')
        self.assertEqual(editor.role, User.Role.EDITOR)
        self.assertTrue(editor.is_verified)
        self.assertEqual(editor.verification_status, User.VerificationStatus.APPROVED)
        self.assertTrue(editor.can_publish)

    def test_new_editor_without_the_box_cannot_publish(self):
        self._new_staff()
        self.assertFalse(User.objects.get(email='ram.thapa@example.com').can_publish)

    def test_eic_cannot_create_an_admin(self):
        response = self._new_staff(role=User.Role.ADMIN)
        self.assertEqual(response.status_code, 200)
        self.assertIn('role', response.context['form'].errors)
        self.assertFalse(User.objects.filter(email='ram.thapa@example.com').exists())

    def test_staff_list_filters(self):
        editor = User.objects.create_user(
            email='filter-editor@example.com', password='pw', first_name='Bishnu', last_name='K', role=User.Role.EDITOR,
        )
        url = reverse('users:manage_staff_list')
        self.assertIn(editor, self.client.get(url, {'role': User.Role.EDITOR}).context['object_list'])
        self.assertNotIn(self.eic, self.client.get(url, {'role': User.Role.EDITOR}).context['object_list'])
        self.assertEqual(list(self.client.get(url, {'q': 'bishnu'}).context['object_list']), [editor])

    def test_change_role_page_and_promotion_to_staff(self):
        author = make_user('promote@example.com', User.Role.VERIFIED_AUTHOR)
        url = reverse('users:change_role', args=[author.pk])
        page = self.client.get(url)
        self.assertEqual(page.context['form'].initial['role'], User.Role.VERIFIED_AUTHOR)
        self.assertNotIn(User.Role.ADMIN, [value for value, _ in page.context['form'].fields['role'].choices])
        response = self.client.post(url, {'role': User.Role.EDITOR})
        self.assertRedirects(response, reverse('users:manage_staff_list'), fetch_redirect_response=False)

    def test_demotion_to_reader_clears_verification(self):
        author = make_user('demote@example.com', User.Role.VERIFIED_AUTHOR, is_verified=True,
                           verification_status=User.VerificationStatus.APPROVED)
        response = self.client.post(reverse('users:change_role', args=[author.pk]), {'role': User.Role.UNVERIFIED})
        self.assertRedirects(response, reverse('users:manage_account_list'), fetch_redirect_response=False)
        author.refresh_from_db()
        self.assertFalse(author.is_verified)
        self.assertEqual(author.verification_status, User.VerificationStatus.NOT_REQUESTED)
        self.assertTrue(author.can_request_verification)

    def test_permissions_list_filters_by_role(self):
        editor = make_user('perm-editor@example.com', User.Role.EDITOR)
        accounts = self.client.get(reverse('users:manage_permissions_list'), {'role': User.Role.EDITOR}).context['accounts']
        self.assertEqual(list(accounts), [editor])


@FAST_PASSWORD_HASHERS
class GroupManagementTests(TestCase):
    """Admin-only Django group screens."""

    def setUp(self):
        self.admin = make_user('admin-groups@example.com', User.Role.ADMIN)
        self.group = Group.objects.create(name='Copy desk')
        self.permission = Permission.objects.get(codename='publish_article', content_type__app_label='articles')
        self.client.force_login(self.admin)

    def test_create_page_groups_permissions_by_app(self):
        page = self.client.get(reverse('users:manage_group_create'))
        self.assertTrue(page.context['is_create'])
        apps = [app for app, _ in page.context['form'].permissions_by_app()]
        self.assertIn('articles', apps)
        self.assertEqual(apps, sorted(apps))

    def test_update_renames_and_sets_permissions(self):
        url = reverse('users:manage_group_update', args=[self.group.pk])
        self.assertFalse(self.client.get(url).context['is_create'])
        self.client.post(url, {'name': 'Publishing desk', 'permissions': [self.permission.pk]})
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, 'Publishing desk')
        self.assertEqual(list(self.group.permissions.all()), [self.permission])
        # Shown ticked when the edit page is opened again.
        form = self.client.get(url).context['form']
        ticked = [perm for _, perms in form.permissions_by_app() for perm, on in perms if on]
        self.assertEqual(ticked, [self.permission])

    def test_invalid_submission_keeps_what_was_ticked(self):
        response = self.client.post(reverse('users:manage_group_create'), {'name': '', 'permissions': [self.permission.pk]})
        ticked = [perm for _, perms in response.context['form'].permissions_by_app() for perm, on in perms if on]
        self.assertEqual(ticked, [self.permission])

    def test_delete(self):
        response = self.client.post(reverse('users:manage_group_delete', args=[self.group.pk]))
        self.assertRedirects(response, reverse('users:manage_group_list'), fetch_redirect_response=False)
        self.assertFalse(Group.objects.filter(pk=self.group.pk).exists())

    def test_assign_groups_to_a_user(self):
        editor = make_user('grouped@example.com', User.Role.EDITOR)
        url = reverse('users:manage_user_groups', args=[editor.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'groups': [self.group.pk]})
        self.assertRedirects(response, reverse('users:manage_permissions_list'), fetch_redirect_response=False)
        self.assertEqual(list(editor.groups.all()), [self.group])
        self.client.post(url, {})
        self.assertFalse(editor.groups.exists())

    def test_eic_cannot_edit_or_delete_groups(self):
        self.client.force_login(make_user('eic-groups@example.com', User.Role.EDITOR_IN_CHIEF))
        self.assertEqual(self.client.post(reverse('users:manage_group_delete', args=[self.group.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('users:manage_group_update', args=[self.group.pk]), {'name': 'x'}).status_code, 403)
        self.assertTrue(Group.objects.filter(name='Copy desk').exists())
