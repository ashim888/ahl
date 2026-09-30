"""Access-control and vulnerability regression tests (September 2026 audit).

1. RouteAccessMatrixTests walks EVERY URL pattern, so a new /manage/ or
   /editorial/ page that forgets its role check fails here without anyone
   having to remember to write a test for it.
2. The rest pin down specific holes found in the audit: private files
   (paywalled PDFs, CVs) that were reachable at public /media/ URLs, an
   Editor-in-Chief being able to take over an Admin account, drafts
   leaking, role mass-assignment, CSRF, open redirects, the stub payment
   gateway on a live server, and a 500 on the image upload endpoint.
"""
import datetime
import importlib
import re
import shutil
import tempfile
from pathlib import Path

from django.apps import apps as django_apps
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from articles.models import Article, ArticleAuthor, Author
from billing.models import SubscriptionPlan, UserSubscription
from users.models import User

FAST_HASHER = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
PDF_BYTES = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def make_user(email, role, **extra):
    return User.objects.create_user(email=email, password='pw', first_name='T', last_name='U', role=role, **extra)


def _all_routes():
    """(path pattern, route name) for every URL in the project."""
    routes = []

    def walk(resolver, prefix=''):
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                routes.append((prefix + str(pattern.pattern), pattern.name))
    walk(get_resolver())
    return routes


def _sample_url(path):
    """A concrete URL for a route pattern — object ids that don't exist,
    since the role check must run before any lookup."""
    def value(match):
        converter, name = match.group(1), match.group(2)
        if converter == 'int' or name in ('pk', 'user_pk'):
            return '999999'
        return 'probe'
    return '/' + re.sub(r'<(?:(\w+):)?(\w+)>', value, path)


# Staff-only areas: editorial roles (Editor, EiC, Admin) only.
STAFF_PREFIXES = ('manage/', 'editorial/', 'verification-queue/', 'ckeditor5/')
# Within them, Editor-in-Chief/Admin only.
SENIOR_ONLY_PREFIXES = (
    'verification-queue/', 'manage/staff/', 'manage/permissions/', 'manage/users/', 'manage/groups/',
    'manage/billing/subscriptions/', 'manage/billing/purchases/', 'manage/billing/plans/', 'editorial/revenue/',
)
# Admin only.
ADMIN_ONLY_PREFIXES = ('manage/groups/',)
ADMIN_ONLY_PATTERNS = (re.compile(r'^manage/users/[^/]+/groups/$'),)


@FAST_HASHER
class RouteAccessMatrixTests(TestCase):
    """Every staff route, every method, every role below it."""

    @classmethod
    def setUpTestData(cls):
        cls.reader = make_user('m-reader@x.test', User.Role.UNVERIFIED)
        cls.author = make_user('m-author@x.test', User.Role.VERIFIED_AUTHOR, is_verified=True)
        cls.editor = make_user('m-editor@x.test', User.Role.EDITOR)
        cls.eic = make_user('m-eic@x.test', User.Role.EDITOR_IN_CHIEF)

    def _staff_routes(self):
        return [
            (path, name) for path, name in _all_routes()
            if path.startswith(STAFF_PREFIXES) and not path.startswith('^')
        ]

    def _responses(self, url, user):
        client = Client(raise_request_exception=False)
        if user:
            client.force_login(user)
        return {'GET': client.get(url), 'POST': client.post(url)}

    def test_there_are_staff_routes_to_check(self):
        self.assertGreater(len(self._staff_routes()), 80)

    def test_anonymous_is_sent_to_login_on_every_staff_route(self):
        for path, name in self._staff_routes():
            url = _sample_url(path)
            for method, response in self._responses(url, None).items():
                with self.subTest(route=name, method=method):
                    if response.status_code == 405:
                        continue
                    self.assertEqual(response.status_code, 302, url)
                    self.assertIn('/login/', response['Location'], url)

    def test_readers_and_authors_are_refused_on_every_staff_route(self):
        for path, name in self._staff_routes():
            url = _sample_url(path)
            for user in (self.reader, self.author):
                for method, response in self._responses(url, user).items():
                    with self.subTest(route=name, role=user.role, method=method):
                        self.assertIn(response.status_code, (403, 405), url)

    def test_plain_editor_is_refused_on_senior_only_routes(self):
        for path, name in self._staff_routes():
            if not path.startswith(SENIOR_ONLY_PREFIXES):
                continue
            url = _sample_url(path)
            for method, response in self._responses(url, self.editor).items():
                with self.subTest(route=name, method=method):
                    self.assertIn(response.status_code, (403, 405), url)

    def test_editor_in_chief_is_refused_on_admin_only_routes(self):
        for path, name in self._staff_routes():
            if not (path.startswith(ADMIN_ONLY_PREFIXES) or any(p.match(path) for p in ADMIN_ONLY_PATTERNS)):
                continue
            url = _sample_url(path)
            for method, response in self._responses(url, self.eic).items():
                with self.subTest(route=name, method=method):
                    self.assertIn(response.status_code, (403, 405), url)

    def test_no_staff_route_errors_for_its_own_staff(self):
        for path, name in self._staff_routes():
            url = _sample_url(path)
            for method, response in self._responses(url, self.eic).items():
                with self.subTest(route=name, method=method):
                    self.assertLess(response.status_code, 500, url)


@FAST_HASHER
class PrivateFileTests(TestCase):
    """Article PDFs and CVs live outside public media and are served only
    through /protected-media/, with an access check on every request."""

    def setUp(self):
        self.public_dir = Path(tempfile.mkdtemp())
        self.private_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.public_dir, True)
        self.addCleanup(shutil.rmtree, self.private_dir, True)
        overrides = override_settings(MEDIA_ROOT=self.public_dir, PRIVATE_MEDIA_ROOT=self.private_dir)
        overrides.enable()
        self.addCleanup(overrides.disable)

        self.reader = make_user('pf-reader@x.test', User.Role.UNVERIFIED)
        self.subscriber = make_user('pf-sub@x.test', User.Role.UNVERIFIED)
        self.editor = make_user('pf-editor@x.test', User.Role.EDITOR)
        plan = SubscriptionPlan.objects.create(name='Monthly', plan_type=SubscriptionPlan.PlanType.choices[0][0],
                                               price=100, duration_days=30)
        UserSubscription.objects.create(user=self.subscriber, plan=plan,
                                        end_date=timezone.localdate() + datetime.timedelta(days=30))
        self.article = Article.objects.create(
            title='Paid Report', slug='paid-report', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=50, html_content='<p>x</p>',
        )
        self.article.pdf_file.save('report.pdf', SimpleUploadedFile('report.pdf', PDF_BYTES), save=True)

    def _get(self, url, user=None):
        client = Client()
        if user:
            client.force_login(user)
        return client.get(url)

    def test_pdf_is_stored_privately_and_linked_through_the_check(self):
        name = self.article.pdf_file.name
        self.assertTrue((self.private_dir / name).is_file())
        self.assertFalse((self.public_dir / name).exists())
        self.assertTrue(self.article.pdf_file.url.startswith('/protected-media/'))
        self.assertEqual(self._get(f'/media/{name}').status_code, 404)

    def test_pdf_refused_to_readers_who_have_not_paid(self):
        for user in (None, self.reader):
            response = self._get(self.article.pdf_file.url, user)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response['Location'], self.article.get_absolute_url())

    def test_pdf_served_to_an_entitled_reader_without_caching(self):
        from billing.models import ArticlePurchase

        ArticlePurchase.objects.create(user=self.reader, article=self.article, amount=50)
        response = self._get(self.article.pdf_file.url, self.reader)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), PDF_BYTES)
        self.assertIn('private', response['Cache-Control'])

    def test_download_link_counts_and_hands_over_the_checked_url(self):
        from billing.models import ArticlePurchase

        ArticlePurchase.objects.create(user=self.reader, article=self.article, amount=50)
        client = Client()
        client.force_login(self.reader)
        response = client.get(reverse('articles:article_download', args=[self.article.slug]))
        self.assertEqual(response['Location'], self.article.pdf_file.url)
        self.article.refresh_from_db()
        self.assertEqual(self.article.download_count, 1)

    def test_draft_pdf_only_for_editorial_staff(self):
        self.article.status = Article.Status.DRAFT
        self.article.save()
        self.assertEqual(self._get(self.article.pdf_file.url, self.subscriber).status_code, 404)
        self.assertEqual(self._get(self.article.pdf_file.url, self.editor).status_code, 200)

    def test_unknown_and_traversal_paths_are_404(self):
        for path in ('/protected-media/articles/nope.pdf', '/protected-media/../ajna_health_lens/settings.py',
                     '/protected-media/%2e%2e/%2e%2e/etc/passwd'):
            self.assertEqual(self._get(path, self.editor).status_code, 404, path)

    def test_cv_only_for_its_owner_and_editorial_staff(self):
        owner = make_user('pf-cv@x.test', User.Role.UNVERIFIED)
        owner.cv_file.save('cv.pdf', SimpleUploadedFile('cv.pdf', PDF_BYTES), save=True)
        self.assertTrue((self.private_dir / owner.cv_file.name).is_file())
        url = owner.cv_file.url
        self.assertEqual(self._get(url).status_code, 404)
        self.assertEqual(self._get(url, self.reader).status_code, 404)
        self.assertEqual(self._get(url, owner).status_code, 200)
        self.assertEqual(self._get(url, self.editor).status_code, 200)

    def test_migration_moves_existing_public_files(self):
        migration = importlib.import_module('articles.migrations.0044_private_files')
        (self.public_dir / 'articles/2026/01').mkdir(parents=True)
        (self.public_dir / 'articles/2026/01/old.pdf').write_bytes(PDF_BYTES)
        Article.objects.filter(pk=self.article.pk).update(pdf_file='articles/2026/01/old.pdf')
        migration._move_files('articles.Article', 'pdf_file', 'MEDIA_ROOT', 'PRIVATE_MEDIA_ROOT')(django_apps, None)
        self.assertTrue((self.private_dir / 'articles/2026/01/old.pdf').is_file())
        self.assertFalse((self.public_dir / 'articles/2026/01/old.pdf').exists())


@FAST_HASHER
class StaffEscalationTests(TestCase):
    """An Editor-in-Chief manages Editors and EiCs, never an Admin — editing
    an Admin's email then resetting the password would take the account."""

    def setUp(self):
        self.eic = make_user('se-eic@x.test', User.Role.EDITOR_IN_CHIEF)
        self.admin = make_user('se-admin@x.test', User.Role.ADMIN)
        self.editor = make_user('se-editor@x.test', User.Role.EDITOR)
        self.client.force_login(self.eic)

    def test_eic_cannot_edit_deactivate_or_demote_an_admin(self):
        self.assertEqual(self.client.get(reverse('users:manage_staff_update', args=[self.admin.pk])).status_code, 404)
        self.client.post(reverse('users:manage_staff_update', args=[self.admin.pk]), {
            'first_name': 'X', 'last_name': 'Y', 'email': 'attacker@x.test', 'role': User.Role.EDITOR, 'is_active': 'on',
        })
        self.client.post(reverse('users:manage_staff_toggle_active', args=[self.admin.pk]))
        response = self.client.post(reverse('users:change_role', args=[self.admin.pk]), {'role': User.Role.EDITOR})
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual((self.admin.email, self.admin.role, self.admin.is_active), ('se-admin@x.test', 'admin', True))

    def test_eic_cannot_make_anyone_admin(self):
        self.client.post(reverse('users:change_role', args=[self.editor.pk]), {'role': User.Role.ADMIN})
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.role, User.Role.EDITOR)

    def test_eic_still_manages_editors_and_admin_manages_admins(self):
        self.assertEqual(self.client.get(reverse('users:manage_staff_update', args=[self.editor.pk])).status_code, 200)
        other_admin = make_user('se-admin2@x.test', User.Role.ADMIN)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('users:manage_staff_update', args=[other_admin.pk])).status_code, 200)

    def test_staff_list_hides_admin_actions_from_eic(self):
        response = self.client.get(reverse('users:manage_staff_list'))
        self.assertNotContains(response, reverse('users:manage_staff_update', args=[self.admin.pk]))
        self.assertContains(response, reverse('users:manage_staff_update', args=[self.editor.pk]))

    def test_editor_cannot_reach_staff_through_the_accounts_screen(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('users:manage_account_update', args=[self.eic.pk]), {
            'first_name': 'X', 'last_name': 'Y', 'email': 'attacker@x.test', 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 404)
        self.eic.refresh_from_db()
        self.assertEqual(self.eic.email, 'se-eic@x.test')


@FAST_HASHER
class ReaderAbuseTests(TestCase):
    """What a logged-in reader or an anonymous visitor might try."""

    def setUp(self):
        self.reader = make_user('ra-reader@x.test', User.Role.UNVERIFIED)

    def test_profile_and_register_ignore_privilege_fields(self):
        self.client.force_login(self.reader)
        self.client.post(reverse('users:profile_edit'), {
            'first_name': 'R', 'last_name': 'D', 'role': 'admin', 'is_staff': 'on', 'is_superuser': 'on', 'is_verified': 'on',
        })
        self.reader.refresh_from_db()
        self.assertEqual((self.reader.role, self.reader.is_staff, self.reader.is_superuser, self.reader.is_verified),
                         (User.Role.UNVERIFIED, False, False, False))
        self.client.logout()
        self.client.post(reverse('users:register'), {
            'first_name': 'M', 'last_name': 'A', 'email': 'ra-new@x.test', 'role': 'admin', 'is_staff': 'on',
            'is_superuser': 'on', 'password1': 'a-strong-passw0rd!', 'password2': 'a-strong-passw0rd!',
        })
        created = User.objects.get(email='ra-new@x.test')
        self.assertEqual((created.role, created.is_staff, created.is_superuser), (User.Role.UNVERIFIED, False, False))

    def test_drafts_and_scheduled_stories_stay_hidden(self):
        draft = Article.objects.create(title='Hidden Zqdraft', slug='hidden-zqdraft', status=Article.Status.DRAFT,
                                       html_content='<p>zqbody</p>')
        scheduled = Article.objects.create(
            title='Hidden Zqsched', slug='hidden-zqsched', status=Article.Status.SCHEDULED,
            published_at=timezone.now() + datetime.timedelta(days=1), html_content='<p>zqbody</p>',
        )
        author = Author.objects.create(name='Only Drafts')
        ArticleAuthor.objects.create(article=draft, author=author)
        for article in (draft, scheduled):
            self.assertEqual(self.client.get(reverse('articles:article_detail', args=[article.slug])).status_code, 404)
            self.assertEqual(self.client.get(reverse('articles:article_citation', args=[article.slug, 'bibtex'])).status_code, 404)
            self.assertEqual(self.client.get(reverse('articles:article_download', args=[article.slug])).status_code, 404)
        for url in ('/feed/', '/feed/atom/', '/sitemap.xml', '/news-sitemap.xml', '/articles/'):
            self.assertNotIn(b'hidden-zq', self.client.get(url).content, url)
        self.assertNotIn(b'hidden-zq', self.client.get('/search/', {'q': 'Hidden'}).content)
        self.assertEqual(self.client.get(reverse('articles:author_detail', args=[author.slug])).status_code, 404)

    def test_state_changing_posts_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reader)
        self.assertEqual(client.post(reverse('users:profile_edit'), {'first_name': 'X'}).status_code, 403)
        self.assertEqual(client.post('/logout/').status_code, 403)

    def test_no_open_redirects(self):
        response = self.client.post('/login/?next=https://evil.example/', {'username': self.reader.email, 'password': 'pw'})
        self.assertNotIn('evil.example', response.get('Location', ''))
        response = self.client.post('/i18n/setlang/', {'language': 'en', 'next': 'https://evil.example/'})
        self.assertNotIn('evil.example', response.get('Location', ''))


@FAST_HASHER
class UploadEndpointTests(TestCase):
    def test_upload_without_a_file_is_a_clean_400_and_get_is_refused(self):
        self.client.force_login(make_user('ue-editor@x.test', User.Role.EDITOR))
        response = self.client.post(reverse('ck_editor_5_upload_file'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertEqual(self.client.get(reverse('ck_editor_5_upload_file')).status_code, 405)


class StubPaymentDeployCheckTests(TestCase):
    """The stub gateway approves every payment — never on a live server."""

    def _errors(self):
        from articles.checks import check_payment_gateway

        return check_payment_gateway(None)

    def test_stub_with_debug_off_is_a_deploy_error(self):
        with override_settings(DEBUG=False, PAYMENT_GATEWAY='stub', ALLOW_STUB_PAYMENTS=False):
            self.assertEqual([e.id for e in self._errors()], ['ajna.E003'])

    def test_real_gateway_debug_or_explicit_staging_opt_in_pass(self):
        for overrides in ({'DEBUG': False, 'PAYMENT_GATEWAY': 'fonepay'}, {'DEBUG': True, 'PAYMENT_GATEWAY': 'stub'},
                          {'DEBUG': False, 'PAYMENT_GATEWAY': 'stub', 'ALLOW_STUB_PAYMENTS': True}):
            with override_settings(**overrides):
                self.assertEqual(self._errors(), [], overrides)


@FAST_HASHER
class AccountEmailLockTests(TestCase):
    """Only EiC/Admin may change a reader's or author's login email —
    otherwise an editor could redirect a subscriber's password reset."""

    def setUp(self):
        self.subscriber = make_user('lock-sub@x.test', User.Role.UNVERIFIED)

    def _post(self, actor):
        self.client.force_login(actor)
        return self.client.post(reverse('users:manage_account_update', args=[self.subscriber.pk]), {
            'first_name': 'New', 'last_name': 'Name', 'email': 'attacker@x.test', 'is_active': 'on',
        })

    def test_plain_editor_can_edit_the_profile_but_not_the_email(self):
        form = self._get_form(make_user('lock-editor@x.test', User.Role.EDITOR))
        self.assertTrue(form.fields['email'].disabled)
        self._post(make_user('lock-editor2@x.test', User.Role.EDITOR))
        self.subscriber.refresh_from_db()
        self.assertEqual((self.subscriber.first_name, self.subscriber.email), ('New', 'lock-sub@x.test'))

    def test_editor_in_chief_can_change_the_email(self):
        self._post(make_user('lock-eic@x.test', User.Role.EDITOR_IN_CHIEF))
        self.subscriber.refresh_from_db()
        self.assertEqual(self.subscriber.email, 'attacker@x.test')

    def _get_form(self, actor):
        self.client.force_login(actor)
        return self.client.get(reverse('users:manage_account_update', args=[self.subscriber.pk])).context['form']


class DebugDefaultTests(TestCase):
    def test_debug_is_off_unless_the_environment_turns_it_on(self):
        import os
        import subprocess
        import sys

        env = {k: v for k, v in os.environ.items() if k != 'DEBUG'}
        env.update({'SECRET_KEY': 'x' * 50, 'DJANGO_SETTINGS_MODULE': 'ajna_health_lens.settings'})
        # dotenv never overrides a variable that is already set, so an empty
        # DEBUG stands in for "not set" regardless of the local .env.
        env['DEBUG'] = ''
        code = 'import django; django.setup(); from django.conf import settings; print(settings.DEBUG)'
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.stdout.strip().splitlines()[-1], 'False', result.stderr[-500:])


@FAST_HASHER
class OrphanMediaCommandTests(TestCase):
    """manage.py quarantine_orphan_media: moves only unreferenced files,
    never deletes, keeps anything referenced from a file field or article HTML."""

    def setUp(self):
        self.media = Path(tempfile.mkdtemp())
        self.orphans = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(shutil.rmtree, self.orphans, True)
        overrides = override_settings(MEDIA_ROOT=self.media, ORPHAN_MEDIA_ROOT=self.orphans)
        overrides.enable()
        self.addCleanup(overrides.disable)

    def _file(self, name, age_days=10):
        import os
        import time

        path = self.media / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
        return path

    def test_moves_only_unreferenced_old_files(self):
        from django.core.management import call_command

        featured = self._file('articles/images/used.jpg')
        inline = self._file('articles/inline/2026/09/inline.png')
        orphan = self._file('manuscripts/2026/08/1_manuscript_v1.pdf')
        fresh = self._file('articles/inline/2026/09/just-uploaded.png', age_days=0)
        Article.objects.create(
            title='Uses files', slug='uses-files', featured_image='articles/images/used.jpg',
            html_content='<figure class="image"><img src="/media/articles/inline/2026/09/inline.png"></figure>',
        )
        call_command('quarantine_orphan_media', '--move', stdout=open('/dev/null', 'w'))
        self.assertTrue(featured.exists() and inline.exists() and fresh.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue((self.orphans / 'manuscripts/2026/08/1_manuscript_v1.pdf').is_file())
        self.assertIn('manuscripts/2026/08/1_manuscript_v1.pdf', (self.orphans / 'manifest.tsv').read_text())

    def test_list_only_by_default(self):
        from django.core.management import call_command

        orphan = self._file('old.jpg')
        call_command('quarantine_orphan_media', stdout=open('/dev/null', 'w'))
        self.assertTrue(orphan.exists())


class DebugDeployCheckTests(TestCase):
    def test_debug_on_is_a_deploy_error_unless_staging_opts_in(self):
        from articles.checks import check_debug_off

        with override_settings(DEBUG=True, ALLOW_DEBUG_DEPLOY=False):
            self.assertEqual([e.id for e in check_debug_off(None)], ['ajna.E004'])
        with override_settings(DEBUG=True, ALLOW_DEBUG_DEPLOY=True):
            self.assertEqual(check_debug_off(None), [])
        with override_settings(DEBUG=False):
            self.assertEqual(check_debug_off(None), [])
