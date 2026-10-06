"""Two-step sign-in for staff (users/two_factor.py)."""
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import User
from .tests import FAST_PASSWORD_HASHERS


def make_user(email, role):
    return User.objects.create_user(email=email, password='Kathmandu-2026!', first_name='Hari', last_name='Rai', role=role)


def current_code(device):
    return TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift).token()


@FAST_PASSWORD_HASHERS
@override_settings(STAFF_TWO_FACTOR_REQUIRED=True)
class TwoStepSetupTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor-2fa@example.com', User.Role.EDITOR)
        self.client.force_login(self.editor)

    def _set_up(self):
        self.client.get(reverse('users:two_step_setup'))
        device = TOTPDevice.objects.get(user=self.editor)
        return self.client.post(reverse('users:two_step_setup'), {'code': f'{current_code(device):06d}'}), device

    def test_staff_are_sent_to_set_it_up_before_anything_else(self):
        for url in (reverse('admin_custom:dashboard'), reverse('articles:manage_article_list'), '/admin/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response.url.startswith(reverse('users:two_step_setup')), url)

    def test_readers_are_not_affected(self):
        reader = make_user('reader-2fa@example.com', User.Role.VERIFIED_AUTHOR)
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('users:profile')).status_code, 200)

    def test_setup_shows_a_qr_code_and_secret(self):
        page = self.client.get(reverse('users:two_step_setup'))
        self.assertContains(page, '<svg')
        self.assertContains(page, 'enter a setup key')

    def test_wrong_code_does_not_turn_it_on(self):
        self.client.get(reverse('users:two_step_setup'))
        response = self.client.post(reverse('users:two_step_setup'), {'code': '000000'})
        self.assertContains(response, 'didn’t match')
        self.assertFalse(TOTPDevice.objects.filter(user=self.editor, confirmed=True).exists())

    def test_confirming_turns_it_on_with_backup_codes(self):
        response, device = self._set_up()
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(len(response.context['codes']), 10)
        self.assertEqual(StaticDevice.objects.get(user=self.editor).token_set.count(), 10)
        self.assertIn('Two-step sign-in is on', mail.outbox[-1].subject)
        self.assertEqual(self.client.get(reverse('admin_custom:dashboard')).status_code, 200)


@FAST_PASSWORD_HASHERS
@override_settings(STAFF_TWO_FACTOR_REQUIRED=True)
class TwoStepSignInTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor-signin@example.com', User.Role.EDITOR)
        self.device = TOTPDevice.objects.create(user=self.editor, name='Authenticator app', confirmed=True)
        self.backup = StaticDevice.objects.create(user=self.editor, name='Backup codes')
        self.backup.token_set.create(token='backup123')
        self.client.force_login(self.editor)  # password step done, code step not

    def test_code_needed_each_sign_in(self):
        response = self.client.get(reverse('articles:manage_article_list'))
        self.assertTrue(response.url.startswith(reverse('users:two_step_verify')))
        response = self.client.post(reverse('users:two_step_verify'), {
            'code': f'{current_code(self.device):06d}', 'next': reverse('articles:manage_article_list'),
        })
        self.assertRedirects(response, reverse('articles:manage_article_list'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('articles:manage_article_list')).status_code, 200)

    def test_wrong_code_is_refused_and_slows_guessing(self):
        response = self.client.post(reverse('users:two_step_verify'), {'code': '123456'})
        self.assertContains(response, 'That code didn’t work')
        # django-otp then makes the next attempt wait (throttling), even a right code.
        response = self.client.post(reverse('users:two_step_verify'), {'code': f'{current_code(self.device):06d}'})
        self.assertContains(response, 'That code didn’t work')

    def test_never_redirects_to_another_site(self):
        response = self.client.post(reverse('users:two_step_verify'), {
            'code': f'{current_code(self.device):06d}', 'next': 'https://evil.example/',
        })
        self.assertRedirects(response, reverse('admin_custom:dashboard'), fetch_redirect_response=False)

    def test_backup_code_works_once_and_warns(self):
        self.client.post(reverse('users:two_step_verify'), {'code': 'backup123'})
        self.assertEqual(self.client.get(reverse('admin_custom:dashboard')).status_code, 200)
        self.assertIn('backup code was used', mail.outbox[-1].subject)
        self.client.logout()
        self.client.force_login(self.editor)
        response = self.client.post(reverse('users:two_step_verify'), {'code': 'backup123'})
        self.assertContains(response, 'That code didn’t work')

    def test_sign_out_is_always_possible(self):
        response = self.client.post(reverse('users:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_new_backup_codes_need_a_verified_session(self):
        self.assertEqual(self.client.post(reverse('users:two_step_backup_codes')).status_code, 403)
        self.client.post(reverse('users:two_step_verify'), {'code': f'{current_code(self.device):06d}'})
        response = self.client.post(reverse('users:two_step_backup_codes'))
        self.assertEqual(len(response.context['codes']), 10)
        self.assertFalse(self.backup.token_set.filter(token='backup123').exists())


@FAST_PASSWORD_HASHERS
class TwoStepResetTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-reset@example.com', User.Role.EDITOR_IN_CHIEF)
        self.editor = make_user('lost-phone@example.com', User.Role.EDITOR)
        self.admin = make_user('admin-reset@example.com', User.Role.ADMIN)
        for user in (self.editor, self.admin):
            TOTPDevice.objects.create(user=user, name='Authenticator app', confirmed=True)

    def test_eic_resets_a_colleagues_lost_phone(self):
        self.client.force_login(self.eic)
        self.assertContains(self.client.get(reverse('users:manage_staff_update', args=[self.editor.pk])), 'Reset (lost phone)')
        self.client.post(reverse('users:manage_staff_reset_two_step', args=[self.editor.pk]))
        self.assertFalse(TOTPDevice.objects.filter(user=self.editor).exists())
        self.assertIn('was reset', mail.outbox[-1].subject)
        self.assertEqual(mail.outbox[-1].to, ['lost-phone@example.com'])

    def test_only_admins_reset_admins_and_editors_reset_nobody(self):
        self.client.force_login(self.eic)
        self.assertEqual(self.client.post(reverse('users:manage_staff_reset_two_step', args=[self.admin.pk])).status_code, 403)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(reverse('users:manage_staff_reset_two_step', args=[self.admin.pk])).status_code, 403)
        self.assertTrue(TOTPDevice.objects.filter(user=self.admin).exists())

    def test_command_for_when_nobody_can_sign_in(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('reset_two_step', 'ADMIN-reset@example.com', stdout=out)
        self.assertIn('Removed 1 device', out.getvalue())

    def test_deploy_check_warns_when_off(self):
        from articles.checks import check_two_factor

        with self.settings(DEBUG=False, STAFF_TWO_FACTOR_REQUIRED=False):
            self.assertEqual([w.id for w in check_two_factor(None)], ['ajna.W004'])


@FAST_PASSWORD_HASHERS
@override_settings(STAFF_TWO_FACTOR_REQUIRED=True)
class TwoStepDoesNotBreakSavingTests(TestCase):
    """Regression: django-otp's OTPMiddleware sets request.user.is_verified
    to a function, which clashed with User.is_verified and crashed any save
    of the signed-in user. We check the session ourselves instead."""

    def test_verified_staff_can_save_their_own_account(self):
        editor = make_user('saver@example.com', User.Role.EDITOR)
        device = TOTPDevice.objects.create(user=editor, name='Authenticator app', confirmed=True)
        self.client.force_login(editor)
        self.client.post(reverse('users:two_step_verify'), {'code': f'{current_code(device):06d}'})
        response = self.client.post(reverse('users:privacy'), {'action': 'emails'})
        self.assertEqual(response.status_code, 302)
        editor.refresh_from_db()
        self.assertIs(editor.is_verified, False)
        self.assertFalse(editor.email_topic_digest)
