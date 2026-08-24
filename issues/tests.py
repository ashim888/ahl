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
