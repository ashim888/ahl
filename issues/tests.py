from django.test import TestCase
from django.urls import reverse

from users.models import User

from .models import Issue


class IssueManageListFilterTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='issue-filter-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_filters_by_published_status(self):
        published = Issue.objects.create(title='Published Issue', slug='published-issue', is_published=True)
        Issue.objects.create(title='Draft Issue', slug='draft-issue', is_published=False)

        response = self.client.get(reverse('issues:manage_issue_list'), {'published': 'yes'})
        self.assertEqual(list(response.context['issues']), [published])

        response = self.client.get(reverse('issues:manage_issue_list'), {'published': 'no'})
        issues = list(response.context['issues'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].title, 'Draft Issue')


class IssueManageCRUDTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='issue-crud-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='issue-crud-reader@example.com', password='pw', first_name='R', last_name='D')

    def test_editor_can_create_an_issue(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('issues:manage_issue_create'), {
            'title': 'Rural Health Access', 'slug': '', 'is_published': 'on',
        })
        self.assertRedirects(response, reverse('issues:manage_issue_list'))
        issue = Issue.objects.get(title='Rural Health Access')
        self.assertEqual(issue.slug, 'rural-health-access')
        self.assertTrue(issue.is_published)

    def test_editor_can_update_an_issue(self):
        issue = Issue.objects.create(title='Original Title', slug='original-title')
        self.client.force_login(self.editor)
        response = self.client.post(reverse('issues:manage_issue_update', args=[issue.pk]), {
            'title': 'Updated Title', 'slug': 'original-title', 'is_published': 'on',
        })
        self.assertRedirects(response, reverse('issues:manage_issue_list'))
        issue.refresh_from_db()
        self.assertEqual(issue.title, 'Updated Title')
        self.assertTrue(issue.is_published)

    def test_editor_can_delete_an_issue(self):
        issue = Issue.objects.create(title='To Delete', slug='to-delete')
        self.client.force_login(self.editor)
        response = self.client.post(reverse('issues:manage_issue_delete', args=[issue.pk]))
        self.assertRedirects(response, reverse('issues:manage_issue_list'))
        self.assertFalse(Issue.objects.filter(pk=issue.pk).exists())

    def test_reader_cannot_create_an_issue(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('issues:manage_issue_create'), {
            'title': 'Should Not Exist', 'slug': '',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Issue.objects.filter(title='Should Not Exist').exists())

    def test_reader_cannot_update_an_issue(self):
        issue = Issue.objects.create(title='Protected Title', slug='protected-title')
        self.client.force_login(self.reader)
        response = self.client.post(reverse('issues:manage_issue_update', args=[issue.pk]), {
            'title': 'Hacked Title', 'slug': 'protected-title',
        })
        self.assertEqual(response.status_code, 403)
        issue.refresh_from_db()
        self.assertEqual(issue.title, 'Protected Title')

    def test_reader_cannot_delete_an_issue(self):
        issue = Issue.objects.create(title='Safe From Deletion', slug='safe-from-deletion')
        self.client.force_login(self.reader)
        response = self.client.post(reverse('issues:manage_issue_delete', args=[issue.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Issue.objects.filter(pk=issue.pk).exists())

    def test_anonymous_visitor_is_redirected_to_login(self):
        # role_required stacks @login_required first — an anonymous request
        # never reaches the role check at all, so it's a redirect-to-login
        # (302), not a 403, unlike the logged-in-but-wrong-role cases above.
        response = self.client.get(reverse('issues:manage_issue_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)


class IssuePublicPageMetaTagsTests(TestCase):
    def test_issue_list_has_a_specific_title(self):
        response = self.client.get(reverse('issues:issue_list'))
        self.assertContains(response, '<title>Issues')

    def test_issue_detail_title_and_description_reflect_the_issue(self):
        issue = Issue.objects.create(
            title='Tuberculosis Coverage', slug='tuberculosis-coverage', is_published=True,
            editorial_note='Ongoing reporting on TB screening and treatment access.',
        )
        response = self.client.get(reverse('issues:issue_detail', args=[issue.slug]))
        content = response.content.decode()
        self.assertIn('<title>Tuberculosis Coverage', content)
        self.assertIn('Ongoing reporting on TB screening', content)

    def test_issue_detail_has_breadcrumb_structured_data(self):
        issue = Issue.objects.create(title='Malaria Series', slug='malaria-series', is_published=True)
        response = self.client.get(reverse('issues:issue_detail', args=[issue.slug]))
        content = response.content.decode()
        self.assertIn('"@type": "BreadcrumbList"', content)
        self.assertIn('Malaria Series', content)
