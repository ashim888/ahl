from django.test import TestCase
from django.urls import reverse

from users.models import User

from .models import EditorialBoardMember


class BoardMemberManageListFilterTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='board-filter-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_filters_by_active_status(self):
        active_member = EditorialBoardMember.objects.create(
            name='Active Member', role_title='Editor', is_active=True,
        )
        EditorialBoardMember.objects.create(
            name='Inactive Member', role_title='Editor', is_active=False,
        )
        response = self.client.get(reverse('editorial_board:manage_member_list'), {'active': 'yes'})
        self.assertEqual(list(response.context['members']), [active_member])

        response = self.client.get(reverse('editorial_board:manage_member_list'), {'active': 'no'})
        members = list(response.context['members'])
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].name, 'Inactive Member')
