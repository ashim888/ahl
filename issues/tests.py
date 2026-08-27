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
