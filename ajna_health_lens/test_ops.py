"""Operations and plumbing: the management commands nothing else runs in
tests (analytics pruning, demo seeding), protected files missing on disk,
and the comment-redirect helpers' fallbacks."""
import datetime
from io import StringIO

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from articles.models import Article, ArticleView
from users.models import User

from .comments_views import COMMENT_FLASH_SESSION_KEY, _comment_target_path, _same_article_next


class PruneAnalyticsCommandTests(TestCase):
    def test_days_option_overrides_the_setting(self):
        article = Article.objects.create(title='Old views', slug='old-views', status=Article.Status.PUBLISHED)
        stale = ArticleView.objects.create(article=article)
        ArticleView.objects.filter(pk=stale.pk).update(viewed_at=timezone.now() - datetime.timedelta(days=40))
        ArticleView.objects.create(article=article)
        out = StringIO()
        call_command('prune_analytics_events', days=30, stdout=out)
        self.assertIn('ArticleView: 1 deleted', out.getvalue())
        self.assertIn('Kept the last 30 days.', out.getvalue())
        self.assertEqual(ArticleView.objects.count(), 1)

    @override_settings(ANALYTICS_RETENTION_DAYS=400)
    def test_default_is_the_retention_setting(self):
        out = StringIO()
        call_command('prune_analytics_events', stdout=out)
        self.assertIn('Kept the last 400 days.', out.getvalue())


class SeedDemoDataCommandTests(TestCase):
    """manage.py seed_demo_data — a fresh install's demo content."""

    def _seed(self):
        call_command('seed_demo_data', stdout=StringIO())
        return (User.objects.count(), Article.objects.count())

    def test_seeds_every_role_and_running_twice_adds_nothing(self):
        first = self._seed()
        roles = set(User.objects.values_list('role', flat=True))
        self.assertTrue({User.Role.ADMIN, User.Role.EDITOR_IN_CHIEF, User.Role.EDITOR, User.Role.UNVERIFIED} <= roles)
        self.assertTrue(Article.objects.filter(status=Article.Status.PUBLISHED).exists())
        self.assertEqual(self._seed(), first)

    def test_demo_accounts_can_log_in_and_land_where_expected(self):
        from articles.management.commands.seed_demo_data import DEMO_PASSWORD

        self._seed()
        editor = User.objects.get(email='editor.gurung@ajnahealthlens.example')
        self.assertTrue(editor.check_password(DEMO_PASSWORD))
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse('articles:manage_article_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('articles:home')).status_code, 200)


class ProtectedFileMissingTests(TestCase):
    def test_file_on_record_but_not_on_disk_is_404(self):
        Article.objects.create(
            title='Lost PDF', slug='lost-pdf', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.OPEN_ACCESS, pdf_file='articles/2026/10/lost.pdf',
        )
        response = self.client.get('/protected-media/articles/2026/10/lost.pdf')
        self.assertEqual(response.status_code, 404)

    def test_paths_outside_private_storage_are_404(self):
        self.assertEqual(self.client.get('/protected-media/../manage.py').status_code, 404)
        self.assertEqual(self.client.get('/protected-media/%2e%2e/manage.py').status_code, 404)


class CommentRedirectHelperTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.article = Article.objects.create(title='Commented', slug='commented-story', status=Article.Status.PUBLISHED)

    def _post(self, data):
        request = self.factory.post('/comments/post/', data)
        request.user = AnonymousUser()
        request.session = SessionStore()
        return request

    def test_unknown_target_gives_no_redirect(self):
        self.assertIsNone(_comment_target_path(self._post({'content_type': 'nope.model', 'object_pk': '1'})))
        self.assertIsNone(_comment_target_path(self._post({'content_type': 'articles.article', 'object_pk': '999999'})))
        self.assertIsNone(_comment_target_path(self._post({})))

    def test_known_target_is_its_canonical_url(self):
        request = self._post({'content_type': 'articles.article', 'object_pk': str(self.article.pk)})
        self.assertEqual(_comment_target_path(request), self.article.get_absolute_url())

    def test_next_is_kept_only_for_the_same_article_on_this_site(self):
        path = self.article.get_absolute_url()
        gift = f'{path}gift/abc123/'
        self.assertEqual(_same_article_next(self._post({'next': gift}), path), gift)
        self.assertEqual(_same_article_next(self._post({'next': '/articles/another-story/'}), path), path)
        self.assertEqual(_same_article_next(self._post({'next': f'https://evil.example{path}'}), path), path)
        self.assertEqual(_same_article_next(self._post({}), path), path)

    def test_bad_confirmation_link_is_refused_without_a_flash(self):
        response = self.client.get(reverse('comments-xtd-confirm', args=['not-a-real-key']))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(COMMENT_FLASH_SESSION_KEY, self.client.session)
