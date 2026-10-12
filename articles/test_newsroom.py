"""Newsroom gaps not covered in articles/tests.py: one-click publish from
the list, corrections/notes/history/restore permissions, autosave refusals,
deleting, preview bylines, list filters, the authors screen, byline parsing,
the deploy checks, the scheduler command and a few helper branches."""
import datetime
import json
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from users.models import User

from . import bylines
from .checks import check_site_base_url
from .content_ads import top_level_paragraph_ends
from .forms import edit_token_for
from .models import Article, ArticleAuthor, ArticleCorrection, ArticleRevision, Author
from .sanitize import sanitize_editorial_html
from .tests import grant_publish
from .video import embed_url, start_seconds


def make_editor(email, publisher=False, role=User.Role.EDITOR):
    user = User.objects.create_user(email=email, password='pw', first_name='N', last_name='E', role=role)
    if publisher:
        grant_publish(user)
    return user


def make_article(slug, status=Article.Status.DRAFT, **extra):
    data = {'title': f'Story {slug}', 'slug': slug, 'status': status, 'html_content': '<p>Body text.</p>'}
    data.update(extra)
    return Article.objects.create(**data)


class QuickPublishTests(TestCase):
    """The Publish / Unpublish button on /manage/articles/."""

    def setUp(self):
        self.publisher = make_editor('quick-publisher@example.com', publisher=True)
        self.client.force_login(self.publisher)

    def _toggle(self, article):
        return self.client.post(reverse('articles:manage_article_quick_publish', args=[article.slug]))

    def test_publish_then_unpublish_records_both(self):
        article = make_article('quick-story')
        response = self._toggle(article)
        self.assertRedirects(response, reverse('articles:manage_article_list'), fetch_redirect_response=False)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)
        self._toggle(article)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)
        actions = list(article.revisions.order_by('created_at').values_list('action', flat=True))
        self.assertEqual(actions, [ArticleRevision.Action.PUBLISHED, ArticleRevision.Action.UNPUBLISHED])
        self.assertEqual(article.revisions.first().user, self.publisher)

    def test_scheduled_story_published_from_the_list_goes_live_now(self):
        article = make_article(
            'scheduled-quick', status=Article.Status.SCHEDULED, published_at=timezone.now() + datetime.timedelta(days=2),
        )
        self._toggle(article)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)
        self.assertLessEqual(article.published_at, timezone.now())


class EditorialRecordPermissionTests(TestCase):
    """Corrections, notes, history and restore — who may change a live story."""

    def setUp(self):
        self.editor = make_editor('plain-editor@example.com')
        self.publisher = make_editor('records-publisher@example.com', publisher=True)
        self.live = make_article('live-story', status=Article.Status.PUBLISHED)
        self.correction = ArticleCorrection.objects.create(article=self.live, note='Fixed a date.')

    def test_only_publishers_remove_a_live_correction(self):
        url = reverse('articles:manage_article_correction_delete', args=[self.correction.pk])
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(ArticleCorrection.objects.filter(pk=self.correction.pk).exists())
        self.client.force_login(self.publisher)
        self.client.post(url)
        self.assertFalse(ArticleCorrection.objects.filter(pk=self.correction.pk).exists())

    def test_empty_note_is_not_added(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('articles:manage_article_note_add', args=[self.live.slug]), {'body': ''}, follow=True)
        self.assertContains(response, 'Write the note before adding it.')
        self.assertFalse(self.live.notes.exists())

    def test_history_with_an_unknown_version_is_404(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('articles:manage_article_history', args=[self.live.slug]), {'compare': '999999'})
        self.assertEqual(response.status_code, 404)

    def test_only_publishers_restore_a_live_story(self):
        from .revisions import record_revision

        revision = record_revision(self.live, self.publisher, ArticleRevision.Action.PUBLISHED)
        Article.objects.filter(pk=self.live.pk).update(html_content='<p>Changed.</p>')
        url = reverse('articles:manage_article_revision_restore', args=[revision.pk])
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.publisher)
        response = self.client.post(url)
        self.assertRedirects(response, reverse('articles:manage_article_update', args=[self.live.slug]), fetch_redirect_response=False)
        self.live.refresh_from_db()
        self.assertEqual(self.live.html_content, '<p>Body text.</p>')


class AutosaveRefusalTests(TestCase):
    def setUp(self):
        self.editor = make_editor('autosave-editor@example.com')
        self.client.force_login(self.editor)
        self.url = reverse('articles:manage_article_autosave')

    def test_live_story_is_never_autosaved(self):
        live = make_article('autosave-live', status=Article.Status.PUBLISHED)
        response = self.client.post(self.url, {'article_pk': live.pk, 'title': 'Half-typed'})
        self.assertEqual(response.status_code, 409)
        live.refresh_from_db()
        self.assertEqual(live.title, 'Story autosave-live')

    def test_stale_tab_does_not_overwrite_newer_changes(self):
        draft = make_article('autosave-draft')
        response = self.client.post(self.url, {'article_pk': draft.pk, 'title': 'Old tab', 'edit_token': '123.000000'})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()['conflict'])
        draft.refresh_from_db()
        self.assertEqual(draft.title, 'Story autosave-draft')
        self.assertNotEqual(edit_token_for(draft), '123.000000')

    def test_nothing_is_saved_without_a_title(self):
        response = self.client.post(self.url, {'title': '   '})
        self.assertEqual(response.status_code, 400)
        self.assertIn('title', response.json()['errors'])
        self.assertFalse(Article.objects.exists())


class ArticleDeleteTests(TestCase):
    def test_editor_deletes_a_draft(self):
        editor = make_editor('delete-editor@example.com')
        draft = make_article('to-delete')
        self.client.force_login(editor)
        response = self.client.post(reverse('articles:manage_article_delete', args=[draft.slug]), follow=True)
        self.assertContains(response, '&quot;Story to-delete&quot; deleted.')
        self.assertFalse(Article.objects.filter(pk=draft.pk).exists())

    def test_only_publishers_delete_a_live_story(self):
        live = make_article('live-delete', status=Article.Status.PUBLISHED)
        self.client.force_login(make_editor('nodelete-editor@example.com'))
        self.assertEqual(self.client.post(reverse('articles:manage_article_delete', args=[live.slug])).status_code, 403)
        self.assertTrue(Article.objects.filter(pk=live.pk).exists())


class PreviewAndListTests(TestCase):
    def setUp(self):
        self.editor = make_editor('list-editor@example.com')
        self.client.force_login(self.editor)

    def test_preview_of_a_saved_story_uses_its_saved_bylines(self):
        article = make_article('preview-source')
        ArticleAuthor.objects.create(article=article, author=Author.objects.create(name='Anita Karki'), order=0)
        response = self.client.post(reverse('articles:manage_article_preview'), {
            'preview_source_pk': article.pk, 'title': article.title, 'slug': article.slug,
            'article_type': Article.ArticleType.NEWS_COMMENTARY, 'access_type': Article.AccessType.OPEN_ACCESS,
            'abstract': 'An abstract.',
        })
        self.assertContains(response, 'Anita Karki')
        self.assertFalse(Article.objects.filter(title='Preview').exists())

    def test_manage_list_filters(self):
        mine = make_article('mine', assigned_to=self.editor, article_type=Article.ArticleType.EDITORIAL)
        hero = make_article('hero-pick', status=Article.Status.PUBLISHED, homepage_section=Article.HomepageSection.HERO)
        other = make_article('malaria-update')
        url = reverse('articles:manage_article_list')

        def listed(**params):
            return set(self.client.get(url, params).context['object_list'])

        self.assertEqual(listed(status=Article.Status.PUBLISHED), {hero})
        self.assertEqual(listed(assigned='me'), {mine})
        self.assertEqual(listed(type=Article.ArticleType.EDITORIAL), {mine})
        self.assertEqual(listed(homepage_section=Article.HomepageSection.HERO), {hero})
        self.assertEqual(listed(q='malaria'), {other})


class AuthorScreenTests(TestCase):
    def setUp(self):
        self.editor = make_editor('authors-editor@example.com')
        self.client.force_login(self.editor)
        self.linked = Author.objects.create(name='Linked Lama', affiliation='BPKIHS', user=make_editor('linked-author@example.com'))
        self.unlinked = Author.objects.create(name='Free Lance', email='freelance@example.com')
        self.retired = Author.objects.create(name='Retired Rai', is_active=False)

    def _listed(self, **params):
        return set(self.client.get(reverse('articles:manage_author_list'), params).context['object_list'])

    def test_list_filters(self):
        self.assertEqual(self._listed(), {self.linked, self.unlinked})
        self.assertEqual(self._listed(q='bpkihs'), {self.linked})
        self.assertEqual(self._listed(q='freelance@'), {self.unlinked})
        self.assertEqual(self._listed(account='yes'), {self.linked})
        self.assertEqual(self._listed(account='no'), {self.unlinked})
        self.assertEqual(self._listed(active='no'), {self.retired})
        self.assertEqual(self._listed(active='all'), {self.linked, self.unlinked, self.retired})

    def test_create_and_update(self):
        response = self.client.post(reverse('articles:manage_author_create'), {'name': 'New Neupane', 'is_active': 'on'}, follow=True)
        self.assertContains(response, 'Author &quot;New Neupane&quot; added.')
        author = Author.objects.get(name='New Neupane')
        article = make_article('credited')
        ArticleAuthor.objects.create(article=article, author=author, order=0)
        url = reverse('articles:manage_author_update', args=[author.pk])
        page = self.client.get(url)
        self.assertEqual([b.article for b in page.context['bylines']], [article])
        self.assertIn(self.editor, page.context['linkable_accounts'])
        response = self.client.post(url, {'name': 'New Neupane', 'affiliation': 'Patan Academy', 'is_active': 'on'}, follow=True)
        self.assertContains(response, '&quot;New Neupane&quot; updated.')
        author.refresh_from_db()
        self.assertEqual(author.affiliation, 'Patan Academy')


class BylineParsingTests(TestCase):
    """articles/bylines.py — what the Authors box may submit."""

    def setUp(self):
        self.article = make_article('byline-story')
        self.author = Author.objects.create(name='Sushma Shah')

    def _parse(self, items):
        return bylines.parse(items if isinstance(items, str) else json.dumps(items), self.article)

    def test_unreadable_input_is_refused(self):
        for raw in ('not json', '{"id": 1}', '[1, 2]', json.dumps([{'id': 'abc'}])):
            with self.assertRaisesMessage(ValidationError, 'could not be read'):
                self._parse(raw)
        self.assertEqual(self._parse(''), [])

    def test_too_many_authors(self):
        with self.assertRaisesMessage(ValidationError, f'at most {bylines.MAX_BYLINES}'):
            self._parse([{'name': f'Person {n}'} for n in range(bylines.MAX_BYLINES + 1)])

    def test_unknown_or_retired_author_is_refused(self):
        retired = Author.objects.create(name='Gone', is_active=False)
        for pk in (999999, retired.pk):
            with self.assertRaisesMessage(ValidationError, 'no longer available'):
                self._parse([{'id': pk}])

    def test_retired_author_already_credited_stays(self):
        retired = Author.objects.create(name='Gone Too', is_active=False)
        ArticleAuthor.objects.create(article=self.article, author=retired, order=0)
        self.assertEqual(self._parse([{'id': retired.pk}])[0]['author'], retired)

    def test_new_author_fields_are_checked(self):
        with self.assertRaisesMessage(ValidationError, 'needs a name'):
            self._parse([{'name': '   '}])
        with self.assertRaisesMessage(ValidationError, 'under 255 characters'):
            self._parse([{'name': 'x' * 256}])
        with self.assertRaisesMessage(ValidationError, 'is not a valid email address'):
            self._parse([{'name': 'Ok Name', 'email': 'not-an-email'}])

    def test_duplicates_are_dropped_and_whitespace_tidied(self):
        entries = self._parse([
            {'id': self.author.pk}, {'id': self.author.pk},
            {'name': '  Hari   Bista ', 'key': 'n1'}, {'name': 'hari bista', 'key': 'n2'},
        ])
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]['name'], 'Hari Bista')

    def test_save_reuses_a_same_name_author_unless_emails_differ(self):
        existing = Author.objects.create(name='Hari Bista', email='hari@example.com')
        created = bylines.save(self.article, self._parse([{'name': 'hari bista', 'key': 'a'}]))
        self.assertEqual(created, {'a': existing.pk})
        created = bylines.save(self.article, self._parse([{'name': 'Hari Bista', 'email': 'other.hari@example.com', 'key': 'b'}]))
        self.assertNotEqual(created['b'], existing.pk)
        self.assertEqual(Author.objects.filter(name__iexact='hari bista').count(), 2)

    def test_save_replaces_the_whole_list_in_order(self):
        second = Author.objects.create(name='Second Person')
        bylines.save(self.article, self._parse([{'id': self.author.pk}, {'id': second.pk, 'corresponding': True}]))
        bylines.save(self.article, self._parse([{'id': second.pk}]))
        rows = list(self.article.articleauthor_set.order_by('order').values_list('author__name', 'is_corresponding'))
        self.assertEqual(rows, [('Second Person', False)])


class DeployCheckTests(TestCase):
    """ajna.E001/E002 — SITE_BASE_URL on a live server."""

    def test_localhost_is_an_error_when_live(self):
        with self.settings(DEBUG=False, SITE_BASE_URL='http://localhost:8000'):
            self.assertEqual([e.id for e in check_site_base_url(None)], ['ajna.E001'])

    def test_plain_http_is_an_error_when_live(self):
        with self.settings(DEBUG=False, SITE_BASE_URL='http://ajnahealthlens.com'):
            self.assertEqual([e.id for e in check_site_base_url(None)], ['ajna.E002'])

    def test_https_domain_passes_and_debug_is_ignored(self):
        with self.settings(DEBUG=False, SITE_BASE_URL='https://ajnahealthlens.com'):
            self.assertEqual(check_site_base_url(None), [])
        with self.settings(DEBUG=True, SITE_BASE_URL='http://localhost:8000'):
            self.assertEqual(check_site_base_url(None), [])


class PublishScheduledCommandTests(TestCase):
    def test_publishes_only_what_is_due(self):
        due = make_article('due-now', status=Article.Status.SCHEDULED, published_at=timezone.now() - datetime.timedelta(minutes=1))
        later = make_article('due-later', status=Article.Status.SCHEDULED, published_at=timezone.now() + datetime.timedelta(hours=1))
        out = StringIO()
        call_command('publish_scheduled', stdout=out)
        self.assertIn('1 scheduled article(s) published.', out.getvalue())
        due.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(due.status, Article.Status.PUBLISHED)
        self.assertEqual(later.status, Article.Status.SCHEDULED)
        self.assertIsNone(due.revisions.get().user)


class HelperBranchTests(TestCase):
    def test_video_start_times(self):
        self.assertEqual(start_seconds('https://youtu.be/dQw4w9WgXcQ?t=1h2m3s'), 3723)
        self.assertEqual(start_seconds('https://youtu.be/dQw4w9WgXcQ?t=soon'), 0)
        self.assertEqual(embed_url('https://youtu.be/dQw4w9WgXcQ?t=1m30s'),
                         'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0&start=90')
        self.assertEqual(embed_url('https://vimeo.com/123'), '')

    def test_only_trusted_chart_scripts_survive(self):
        html = sanitize_editorial_html(
            '<script type="text/javascript" src="https://d3js.org/d3.v7.min.js" onload="x()"></script>'
            '<script src="https://evil.example/x.js"></script>',
        )
        self.assertIn('src="https://d3js.org/d3.v7.min.js"', html)
        self.assertIn('type="text/javascript"', html)
        self.assertNotIn('evil.example', html)
        self.assertNotIn('onload', html)

    def test_ads_skip_paragraph_tags_inside_scripts(self):
        html = '<p>One</p><script>var s = "<p>not real</p>";</script><p>Two</p>'
        ends = top_level_paragraph_ends(html)
        self.assertEqual([html[:end][-10:] for end in ends], ['<p>One</p>', '<p>Two</p>'])
        # An unclosed script swallows the rest: no ad slot inside it.
        self.assertEqual(top_level_paragraph_ends('<p>One</p><script>never closed <p>x</p>'), [len('<p>One</p>')])


class CorrectionsPageTests(TestCase):
    """/corrections/ — the public record of corrections."""

    def setUp(self):
        self.live = make_article('corrected-story', status=Article.Status.PUBLISHED)
        self.draft = make_article('draft-corrected')
        ArticleCorrection.objects.create(article=self.live, kind=ArticleCorrection.Kind.CORRECTION, note='Fixed the dose figure.')
        ArticleCorrection.objects.create(article=self.live, kind=ArticleCorrection.Kind.UPDATE, note='Added the ministry response.')
        ArticleCorrection.objects.create(article=self.draft, note='Not public yet.')

    def test_lists_corrections_on_published_stories_newest_first(self):
        response = self.client.get(reverse('articles:correction_list'))
        notes = [c.note for c in response.context['corrections']]
        self.assertEqual(notes, ['Added the ministry response.', 'Fixed the dose figure.'])
        self.assertContains(response, f'{self.live.get_absolute_url()}#corrections')

    def test_filter_by_kind(self):
        response = self.client.get(reverse('articles:correction_list'), {'kind': 'correction'})
        self.assertEqual([c.note for c in response.context['corrections']], ['Fixed the dose figure.'])

    def test_linked_from_the_article_footer_and_sitemap(self):
        self.assertContains(self.client.get(self.live.get_absolute_url()), reverse('articles:correction_list'))
        self.assertContains(self.client.get('/sitemap.xml'), '/corrections/')
