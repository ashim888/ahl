from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from articles.models import Article
from users.models import User

from .models import Section


def make_article(slug, section=None, status=Article.Status.PUBLISHED):
    return Article.objects.create(
        title=slug.replace('-', ' ').title(), slug=slug, abstract='Abstract',
        article_type=Article.ArticleType.NEWS_COMMENTARY, status=status, section=section,
    )


def make_editor(email='section-editor@example.com'):
    return User.objects.create_user(email=email, password='pw', first_name='E', last_name='D', role=User.Role.EDITOR)


def make_reader(email='section-reader@example.com'):
    return User.objects.create_user(email=email, password='pw', first_name='R', last_name='D')


# Fixture slugs below are deliberately distinct from the seed migration's
# real slugs (sections/migrations/0002_seed_primary_nav.py, e.g. "journal",
# "clinical-practice") — the test DB has that migration already applied, so
# reusing a seeded slug would collide with the unique constraint.


class SectionModelTests(TestCase):
    def test_top_level_section_is_valid(self):
        section = Section(name_en='Test Journal', name_ne='जर्नल', slug='test-journal')
        section.full_clean()  # should not raise

    def test_child_of_top_level_is_valid(self):
        top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        child = Section(name_en='Test Clinical Practice', slug='test-clinical-practice', parent=top)
        child.full_clean()  # should not raise

    def test_third_level_nesting_is_rejected(self):
        top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        child = Section.objects.create(name_en='Test Clinical Practice', slug='test-clinical-practice', parent=top)
        grandchild = Section(name_en='Too Deep', slug='test-too-deep', parent=child)
        with self.assertRaises(ValidationError):
            grandchild.full_clean()

    def test_section_cannot_be_its_own_parent(self):
        section = Section.objects.create(name_en='Test Journal', slug='test-journal')
        section.parent = section
        with self.assertRaises(ValidationError):
            section.full_clean()

    def test_link_override_on_a_child_section_is_rejected(self):
        top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        child = Section(name_en='Bad', slug='test-bad', parent=top, link_url_name='training:course_list')
        with self.assertRaises(ValidationError):
            child.full_clean()

    def test_link_override_section_cannot_gain_children(self):
        top = Section.objects.create(name_en='Test Training', slug='test-training', link_url_name='training:course_list')
        child = Section(name_en='Sub', slug='test-sub', parent=top)
        # Creating the child itself is fine (child has no link_url_name) —
        # the constraint is on the *parent* having both a link override and children.
        child.full_clean()
        child.save()
        top.link_url_name = 'training:course_list'
        with self.assertRaises(ValidationError):
            top.full_clean()

    def test_nav_url_for_link_override_section(self):
        section = Section.objects.create(name_en='Test Training', slug='test-training', link_url_name='training:course_list')
        self.assertEqual(section.nav_url, reverse('training:course_list'))

    def test_nav_url_for_content_section(self):
        section = Section.objects.create(name_en='Test Journal', slug='test-journal-nav')
        self.assertEqual(section.nav_url, reverse('sections:section_detail', args=['test-journal-nav']))


class SectionManageAccessTests(TestCase):
    def setUp(self):
        self.editor = make_editor()
        self.reader = make_reader()

    def test_editor_can_list_sections(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('sections:manage_section_list'))
        self.assertEqual(response.status_code, 200)

    def test_reader_cannot_access_section_management(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('sections:manage_section_list'))
        self.assertEqual(response.status_code, 403)

    def test_editor_can_create_a_top_level_section(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('sections:manage_section_create'), {
            'name_en': 'Test Journal', 'name_ne': 'जर्नल', 'slug': 'test-journal', 'order': 0, 'is_active': 'on',
        })
        self.assertRedirects(response, reverse('sections:manage_section_list'))
        section = Section.objects.get(slug='test-journal')
        self.assertEqual(section.name_en, 'Test Journal')
        self.assertEqual(section.name_ne, 'जर्नल')
        self.assertIsNone(section.parent)

    def test_create_rejects_a_third_nesting_level(self):
        top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        child = Section.objects.create(name_en='Test Clinical Practice', slug='test-clinical-practice', parent=top)
        self.client.force_login(self.editor)
        response = self.client.post(reverse('sections:manage_section_create'), {
            'name_en': 'Too Deep', 'slug': 'test-too-deep', 'parent': child.pk, 'order': 0,
        })
        self.assertEqual(response.status_code, 200)  # re-rendered with an error, not redirected
        self.assertFalse(Section.objects.filter(slug='test-too-deep').exists())

    def test_parent_dropdown_only_offers_top_level_sections(self):
        top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        child = Section.objects.create(name_en='Test Clinical Practice', slug='test-clinical-practice', parent=top)
        self.client.force_login(self.editor)
        response = self.client.get(reverse('sections:manage_section_create'))
        self.assertIn(top, response.context['form'].fields['parent'].queryset)
        self.assertNotIn(child, response.context['form'].fields['parent'].queryset)

    def test_editor_can_update_a_section(self):
        section = Section.objects.create(name_en='Test Journal', slug='test-journal')
        self.client.force_login(self.editor)
        response = self.client.post(reverse('sections:manage_section_update', args=[section.pk]), {
            'name_en': 'The Test Journal', 'slug': 'test-journal', 'order': 0,
        })
        self.assertRedirects(response, reverse('sections:manage_section_list'))
        section.refresh_from_db()
        self.assertEqual(section.name_en, 'The Test Journal')

    def test_editor_can_delete_a_section(self):
        section = Section.objects.create(name_en='Test Journal', slug='test-journal')
        self.client.force_login(self.editor)
        response = self.client.post(reverse('sections:manage_section_delete', args=[section.pk]))
        self.assertRedirects(response, reverse('sections:manage_section_list'))
        self.assertFalse(Section.objects.filter(pk=section.pk).exists())

    def test_deleting_a_top_level_section_also_deletes_its_children(self):
        top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        Section.objects.create(name_en='Test Clinical Practice', slug='test-clinical-practice', parent=top)
        self.client.force_login(self.editor)
        self.client.post(reverse('sections:manage_section_delete', args=[top.pk]))
        self.assertFalse(Section.objects.filter(slug='test-clinical-practice').exists())

    def test_delete_confirmation_page_shows_child_count(self):
        top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        Section.objects.create(name_en='Test Clinical Practice', slug='test-clinical-practice', parent=top)
        Section.objects.create(name_en='Test Public Health', slug='test-public-health', parent=top)
        self.client.force_login(self.editor)
        response = self.client.get(reverse('sections:manage_section_delete', args=[top.pk]))
        self.assertContains(response, '2 sub-section')

    def test_filters_by_active_status(self):
        # The seed migration's 7 top-level sections are all active by
        # default too, so this checks membership rather than exact equality.
        active = Section.objects.create(name_en='Test Active One', slug='test-active-one', is_active=True)
        inactive = Section.objects.create(name_en='Test Inactive One', slug='test-inactive-one', is_active=False)
        self.client.force_login(self.editor)
        response = self.client.get(reverse('sections:manage_section_list'), {'active': 'yes'})
        self.assertIn(active, response.context['sections'])
        self.assertNotIn(inactive, response.context['sections'])


class SeedPrimaryNavMigrationTests(TestCase):
    """Confirms the data migration (sections/migrations/0002_seed_primary_nav.py)
    produced the expected structure — the test DB has every migration applied
    before tests run, so this just queries the result rather than driving
    the migration executor directly (no existing precedent in this project
    for that; other data migrations here are verified the same way).
    """

    def test_seeds_five_subject_sections_plus_training_and_issues(self):
        top_level = list(Section.objects.filter(parent__isnull=True).order_by('order').values_list('slug', flat=True))
        self.assertEqual(
            top_level,
            ['journal', 'policy-economy', 'health-tech', 'service-delivery', 'opinions', 'training', 'issues'],
        )

    def test_subject_sections_have_their_seeded_children(self):
        journal = Section.objects.get(slug='journal')
        children = list(journal.children.order_by('order').values_list('slug', flat=True))
        self.assertEqual(children, ['clinical-practice', 'public-health', 'medical-education', 'traditional-medicine'])

    def test_training_and_issues_are_link_overrides_with_no_children(self):
        training = Section.objects.get(slug='training')
        issues = Section.objects.get(slug='issues')
        self.assertEqual(training.link_url_name, 'training:course_list')
        self.assertEqual(issues.link_url_name, 'issues:issue_list')
        self.assertEqual(training.children.count(), 0)
        self.assertEqual(issues.children.count(), 0)

    def test_top_level_subject_headers_have_seeded_nepali_names(self):
        journal = Section.objects.get(slug='journal')
        self.assertEqual(journal.name_ne, 'जर्नल')

    def test_seeded_sections_pass_model_validation(self):
        for section in Section.objects.all():
            section.full_clean()  # should not raise for any seeded row


class SectionMoveTests(TestCase):
    def setUp(self):
        self.editor = make_editor()
        self.reader = make_reader()
        self.top = Section.objects.create(name_en='Test Journal', slug='test-journal')
        self.child_a = Section.objects.create(name_en='A Test Clinical Practice', slug='test-child-a', parent=self.top)
        self.child_b = Section.objects.create(name_en='B Test Public Health', slug='test-child-b', parent=self.top)

    def test_move_down_swaps_with_next_sibling(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('sections:manage_section_move', args=[self.child_a.pk, 'down']))
        self.child_a.refresh_from_db()
        self.child_b.refresh_from_db()
        self.assertGreater(self.child_a.order, self.child_b.order)

    def test_move_up_swaps_with_previous_sibling(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('sections:manage_section_move', args=[self.child_b.pk, 'up']))
        self.child_a.refresh_from_db()
        self.child_b.refresh_from_db()
        self.assertLess(self.child_b.order, self.child_a.order)

    def test_top_level_and_child_orders_are_independent(self):
        # A second top-level section shares order=0 with self.top initially —
        # moving a *child* must never touch the top-level siblings' order.
        other_top = Section.objects.create(name_en='Test Policy', slug='test-policy')
        self.client.force_login(self.editor)
        self.client.post(reverse('sections:manage_section_move', args=[self.child_b.pk, 'up']))
        self.top.refresh_from_db()
        other_top.refresh_from_db()
        self.assertEqual(self.top.order, 0)
        self.assertEqual(other_top.order, 0)

    def test_moving_first_sibling_up_is_a_safe_noop(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('sections:manage_section_move', args=[self.child_a.pk, 'up']))
        self.assertRedirects(response, reverse('sections:manage_section_list'))
        ordered_slugs = list(
            Section.objects.filter(parent=self.top).order_by('order', 'name').values_list('slug', flat=True),
        )
        self.assertEqual(ordered_slugs, ['test-child-a', 'test-child-b'])

    def test_invalid_direction_404s(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('sections:manage_section_move', args=[self.child_a.pk, 'sideways']))
        self.assertEqual(response.status_code, 404)

    def test_reader_cannot_move(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('sections:manage_section_move', args=[self.child_a.pk, 'down']))
        self.assertEqual(response.status_code, 403)


class SectionDetailViewTests(TestCase):
    def setUp(self):
        self.top = Section.objects.create(name_en='Test Top', slug='test-top')
        self.child = Section.objects.create(name_en='Test Child', slug='test-child', parent=self.top)
        self.other_top = Section.objects.create(name_en='Test Other', slug='test-other')

    def test_top_level_landing_page_aggregates_own_and_child_articles(self):
        own = make_article('test-own-article', section=self.top)
        child_article = make_article('test-child-article', section=self.child)
        unrelated = make_article('test-unrelated-article', section=self.other_top)
        response = self.client.get(reverse('sections:section_detail', args=['test-top']))
        self.assertEqual(response.status_code, 200)
        articles = list(response.context['articles'])
        self.assertIn(own, articles)
        self.assertIn(child_article, articles)
        self.assertNotIn(unrelated, articles)

    def test_leaf_landing_page_shows_only_its_own_articles(self):
        own = make_article('test-leaf-own-article', section=self.child)
        parent_article = make_article('test-parent-article', section=self.top)
        response = self.client.get(reverse('sections:section_detail', args=['test-child']))
        articles = list(response.context['articles'])
        self.assertIn(own, articles)
        self.assertNotIn(parent_article, articles)

    def test_draft_articles_are_excluded(self):
        draft = make_article('test-draft-article', section=self.top, status=Article.Status.DRAFT)
        response = self.client.get(reverse('sections:section_detail', args=['test-top']))
        self.assertNotIn(draft, list(response.context['articles']))

    def test_link_override_section_has_no_landing_page(self):
        Section.objects.create(name_en='Test Training', slug='test-training-detail', link_url_name='training:course_list')
        response = self.client.get(reverse('sections:section_detail', args=['test-training-detail']))
        self.assertEqual(response.status_code, 404)

    def test_inactive_section_has_no_landing_page(self):
        Section.objects.create(name_en='Test Inactive', slug='test-inactive-detail', is_active=False)
        response = self.client.get(reverse('sections:section_detail', args=['test-inactive-detail']))
        self.assertEqual(response.status_code, 404)

    def test_page_title_reflects_section_name(self):
        response = self.client.get(reverse('sections:section_detail', args=['test-top']))
        self.assertContains(response, '<title>Test Top')


class PrimaryNavRenderingTests(TestCase):
    """`nav_sections` (journal_settings context processor) drives the shared
    templates/includes/main_nav.html partial on every base.html page — these
    hit a real page (not '/', which is the pre-launch coming-soon
    placeholder and doesn't extend base.html) and check the rendered HTML
    against the DB, not just the context processor's queryset in isolation.
    """

    def setUp(self):
        self.home_url = reverse('articles:home')

    def test_active_top_level_section_appears_in_nav(self):
        Section.objects.create(name_en='Test Nav Topic', slug='test-nav-topic', order=999)
        response = self.client.get(self.home_url)
        self.assertContains(response, 'TEST NAV TOPIC')

    def test_inactive_top_level_section_is_hidden_from_nav(self):
        Section.objects.create(name_en='Test Nav Hidden', slug='test-nav-hidden', is_active=False)
        response = self.client.get(self.home_url)
        self.assertNotContains(response, 'TEST NAV HIDDEN')

    def test_child_section_appears_under_its_parent(self):
        top = Section.objects.create(name_en='Test Nav Parent', slug='test-nav-parent', order=999)
        Section.objects.create(name_en='Test Nav Child', slug='test-nav-child', parent=top)
        response = self.client.get(self.home_url)
        self.assertContains(response, 'TEST NAV CHILD')

    def test_inactive_child_is_hidden_but_parent_still_shows(self):
        top = Section.objects.create(name_en='Test Nav Parent Two', slug='test-nav-parent-two', order=999)
        Section.objects.create(name_en='Test Nav Hidden Child', slug='test-nav-hidden-child', parent=top, is_active=False)
        response = self.client.get(self.home_url)
        self.assertContains(response, 'TEST NAV PARENT TWO')
        self.assertNotContains(response, 'TEST NAV HIDDEN CHILD')

    def test_link_override_section_points_at_its_own_feature_url(self):
        Section.objects.create(name_en='Test Nav Training', slug='test-nav-training', link_url_name='training:course_list')
        response = self.client.get(self.home_url)
        self.assertContains(response, reverse('training:course_list'))

    def test_content_section_links_to_its_landing_page(self):
        section = Section.objects.create(name_en='Test Nav Landing', slug='test-nav-landing', order=999)
        response = self.client.get(self.home_url)
        self.assertContains(response, reverse('sections:section_detail', args=[section.slug]))
