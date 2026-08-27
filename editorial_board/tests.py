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


class BoardMemberMoveTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='board-move-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='board-move-reader@example.com', password='pw', first_name='R', last_name='D')
        # All default order=0 — the common case for a freshly created list,
        # and the exact scenario the normalize-then-swap logic exists for.
        self.first = EditorialBoardMember.objects.create(name='A First', role_title='Editor')
        self.second = EditorialBoardMember.objects.create(name='B Second', role_title='Editor')
        self.third = EditorialBoardMember.objects.create(name='C Third', role_title='Editor')

    def test_move_down_swaps_with_next_member(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('editorial_board:manage_member_move', args=[self.first.pk, 'down']))
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertGreater(self.first.order, self.second.order)

    def test_move_up_swaps_with_previous_member(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('editorial_board:manage_member_move', args=[self.third.pk, 'up']))
        self.second.refresh_from_db()
        self.third.refresh_from_db()
        self.assertLess(self.third.order, self.second.order)

    def test_moving_first_member_up_is_a_safe_noop(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('editorial_board:manage_member_move', args=[self.first.pk, 'up']))
        self.assertRedirects(response, reverse('editorial_board:manage_member_list'))
        ordered_names = list(EditorialBoardMember.objects.order_by('order', 'name').values_list('name', flat=True))
        self.assertEqual(ordered_names, ['A First', 'B Second', 'C Third'])

    def test_invalid_direction_404s(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('editorial_board:manage_member_move', args=[self.first.pk, 'sideways']))
        self.assertEqual(response.status_code, 404)

    def test_reader_cannot_move(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('editorial_board:manage_member_move', args=[self.first.pk, 'down']))
        self.assertEqual(response.status_code, 403)


class PublicPageMetaTagsTests(TestCase):
    def test_default_tab_title_is_about(self):
        response = self.client.get(reverse('editorial_board:public_list'))
        self.assertContains(response, '<title>About')

    def test_board_tab_has_its_own_title(self):
        response = self.client.get(reverse('editorial_board:public_list'), {'tab': 'board'})
        self.assertContains(response, '<title>Editorial Board')

    def test_policies_tab_has_its_own_title(self):
        response = self.client.get(reverse('editorial_board:public_list'), {'tab': 'policies'})
        self.assertContains(response, '<title>Policies')
