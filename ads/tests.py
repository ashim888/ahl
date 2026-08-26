import datetime
import io

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from users.models import User

from .forms import AdSlotForm
from .models import AdEvent, AdSettings, AdSlot
from .services import get_ad_for_request, get_ad_for_zone, record_click, record_impression


def demo_image(name='ad.jpg', size=(10, 10)):
    buffer = io.BytesIO()
    Image.new('RGB', size).save(buffer, format='JPEG')
    return ContentFile(buffer.getvalue(), name=name)


def make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, is_active=True, start_date=None, end_date=None, sponsor_name='Test Sponsor'):
    return AdSlot.objects.create(
        sponsor_name=sponsor_name, zone=zone, image=demo_image(), link_url='https://example.com/sponsor',
        is_active=is_active, start_date=start_date or timezone.localdate(), end_date=end_date,
    )


class AdSelectionTests(TestCase):
    def test_active_ad_in_zone_is_selected(self):
        ad = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1)
        self.assertEqual(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE_1), ad)

    def test_wrong_zone_is_not_selected(self):
        make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR)
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE_1))

    def test_inactive_ad_is_not_selected(self):
        make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, is_active=False)
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE_1))

    def test_not_yet_started_ad_is_not_selected(self):
        make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, start_date=timezone.localdate() + datetime.timedelta(days=1))
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE_1))

    def test_expired_ad_is_not_selected(self):
        make_ad(
            zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1,
            start_date=timezone.localdate() - datetime.timedelta(days=10),
            end_date=timezone.localdate() - datetime.timedelta(days=1),
        )
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE_1))

    def test_ad_with_no_end_date_runs_indefinitely(self):
        ad = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, end_date=None)
        self.assertEqual(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE_1), ad)


class ImpressionAndClickTrackingTests(TestCase):
    def test_record_impression_increments(self):
        ad = make_ad()
        record_impression(ad)
        record_impression(ad)
        ad.refresh_from_db()
        self.assertEqual(ad.impression_count, 2)

    def test_record_click_increments(self):
        ad = make_ad()
        record_click(ad)
        ad.refresh_from_db()
        self.assertEqual(ad.click_count, 1)

    def test_click_view_redirects_and_counts(self):
        ad = make_ad()
        response = self.client.get(reverse('ads:click', args=[ad.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, ad.link_url)
        ad.refresh_from_db()
        self.assertEqual(ad.click_count, 1)

    def test_record_impression_writes_event_log_row(self):
        ad = make_ad()
        record_impression(ad)
        self.assertEqual(AdEvent.objects.filter(ad_slot=ad, event_type=AdEvent.EventType.IMPRESSION).count(), 1)

    def test_record_click_writes_event_log_row(self):
        ad = make_ad()
        record_click(ad)
        self.assertEqual(AdEvent.objects.filter(ad_slot=ad, event_type=AdEvent.EventType.CLICK).count(), 1)


class AdSlotCtrTests(TestCase):
    def test_ctr_is_none_with_no_impressions(self):
        ad = make_ad()
        self.assertIsNone(ad.ctr)

    def test_ctr_is_computed_from_counts(self):
        ad = make_ad()
        for _ in range(4):
            record_impression(ad)
        record_click(ad)
        ad.refresh_from_db()
        self.assertEqual(ad.ctr, 25.0)


class AdSlotManageTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='ad-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='ad-reader@example.com', password='pw', first_name='R', last_name='D')

    def test_editorial_staff_can_list_ads(self):
        make_ad()
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_adslot_list'))
        self.assertEqual(response.status_code, 200)

    def test_reader_cannot_access_ad_management(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('ads:manage_adslot_list'))
        self.assertEqual(response.status_code, 403)

    def test_toggle_active(self):
        ad = make_ad(is_active=True)
        self.client.force_login(self.editor)
        self.client.post(reverse('ads:manage_adslot_toggle_active', args=[ad.pk]))
        ad.refresh_from_db()
        self.assertFalse(ad.is_active)

    # Zone-level impressions/clicks/CTR stats moved to the separate
    # /manage/ads/analytics/ page (August 2026) — see
    # AdSlotAnalyticsOverviewTests.test_zone_stats_and_window_totals.


class AdSlotListFilterTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='ad-filter-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_filters_by_zone(self):
        homepage_ad = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, sponsor_name='Homepage Sponsor')
        make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR, sponsor_name='Sidebar Sponsor')
        response = self.client.get(reverse('ads:manage_adslot_list'), {'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE_1})
        ads = list(response.context['ad_slots'])
        self.assertEqual(ads, [homepage_ad])

    def test_filters_by_active_status(self):
        active_ad = make_ad(is_active=True, sponsor_name='Active Sponsor')
        make_ad(is_active=False, sponsor_name='Inactive Sponsor')
        response = self.client.get(reverse('ads:manage_adslot_list'), {'active': 'yes'})
        self.assertEqual(list(response.context['ad_slots']), [active_ad])

        response = self.client.get(reverse('ads:manage_adslot_list'), {'active': 'no'})
        ads = list(response.context['ad_slots'])
        self.assertEqual(len(ads), 1)
        self.assertEqual(ads[0].sponsor_name, 'Inactive Sponsor')

    def test_list_page_has_no_zone_stats_or_chart(self):
        # Split out to the dedicated Analytics page (AdSlotAnalyticsOverviewTests
        # below) — the list page is just the searchable/filterable/paginated list.
        make_ad()
        response = self.client.get(reverse('ads:manage_adslot_list'))
        self.assertNotIn('zone_stats', response.context)
        self.assertNotContains(response, 'Daily Impressions')
        self.assertContains(response, 'Analytics →')


class AdSlotAnalyticsTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='ad-analytics-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='ad-analytics-reader@example.com', password='pw', first_name='R', last_name='D')

    def test_editorial_staff_can_view_analytics(self):
        ad = make_ad()
        record_impression(ad)
        record_click(ad)
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_adslot_analytics', args=[ad.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['window_impressions'], 1)
        self.assertEqual(response.context['window_clicks'], 1)
        self.assertEqual(response.context['window_ctr'], 100.0)

    def test_reader_cannot_view_analytics(self):
        ad = make_ad()
        self.client.force_login(self.reader)
        response = self.client.get(reverse('ads:manage_adslot_analytics', args=[ad.pk]))
        self.assertEqual(response.status_code, 403)


class AdSlotAnalyticsOverviewTests(TestCase):
    """The sitewide /manage/ads/analytics/ page — a top chart (every ad,
    every zone) plus a filterable panel below it (all zones' totals by
    default, or one zone's ads once picked). Split out from AdSlotListView
    (AdSlotListFilterTests above), which used to compute the same zone
    breakdown inline on the list page.
    """

    def setUp(self):
        self.editor = User.objects.create_user(
            email='ad-overview-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(
            email='ad-overview-reader@example.com', password='pw', first_name='R', last_name='D',
        )

    def test_reader_cannot_view(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('ads:manage_ads_analytics'))
        self.assertEqual(response.status_code, 403)

    def test_chart_defaults_to_7_days(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'))
        self.assertEqual(response.context['chart_days'], 7)
        self.assertEqual(len(response.context['daily_stats']), 7)
        self.assertEqual(response.context['filter_days'], 7)

    def test_chart_days_param_changes_window(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'), {'chart_days': 30})
        self.assertEqual(response.context['chart_days'], 30)
        self.assertEqual(len(response.context['daily_stats']), 30)

    def test_invalid_chart_days_falls_back_to_default(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'), {'chart_days': 'not-a-number'})
        self.assertEqual(response.context['chart_days'], 7)

    def test_window_totals(self):
        ad = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Leaderboard Sponsor')
        other = make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR, sponsor_name='Sidebar Sponsor')
        record_impression(ad)
        record_impression(ad)
        record_click(ad)
        record_impression(other)

        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['window_impressions'], 3)
        self.assertEqual(response.context['window_clicks'], 1)
        self.assertEqual(response.context['all_time_impressions'], 3)
        self.assertEqual(response.context['all_time_clicks'], 1)

    def test_default_view_shows_one_row_per_zone_no_chart(self):
        ad = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Leaderboard Sponsor')
        record_impression(ad)
        record_impression(ad)
        record_click(ad)

        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'))
        self.assertEqual(response.context['filter_zone'], '')
        self.assertIsNone(response.context['filtered_daily_stats'])
        rows_by_label = {r['label']: r for r in response.context['performance_rows']}
        leaderboard_row = rows_by_label[AdSlot.Zone.HEADER_LEADERBOARD.label]
        self.assertEqual(leaderboard_row['impressions'], 2)
        self.assertEqual(leaderboard_row['clicks'], 1)
        self.assertEqual(leaderboard_row['ctr'], 50.0)
        # One row per zone in the choices list, not just zones with an ad.
        self.assertEqual(len(response.context['performance_rows']), len(AdSlot.Zone.choices))

    def test_filtering_by_zone_shows_ads_in_that_zone_and_a_chart(self):
        low = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Low Clicks')
        high = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='High Clicks')
        make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR, sponsor_name='Different Zone')
        record_click(low)
        for _ in range(3):
            record_click(high)

        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'), {'filter_zone': AdSlot.Zone.HEADER_LEADERBOARD})
        self.assertEqual(response.context['filter_zone'], AdSlot.Zone.HEADER_LEADERBOARD)
        self.assertEqual(response.context['filter_zone_label'], AdSlot.Zone.HEADER_LEADERBOARD.label)
        self.assertIsNotNone(response.context['filtered_daily_stats'])

        rows = list(response.context['performance_rows'])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['label'], 'High Clicks')
        self.assertEqual(rows[0]['clicks'], 3)
        self.assertNotContains(response, 'Different Zone')

    def test_filter_days_independent_of_chart_days(self):
        self.client.force_login(self.editor)
        response = self.client.get(
            reverse('ads:manage_ads_analytics'), {'chart_days': 30, 'filter_zone': AdSlot.Zone.HEADER_LEADERBOARD, 'filter_days': 14},
        )
        self.assertEqual(response.context['chart_days'], 30)
        self.assertEqual(response.context['filter_days'], 14)
        self.assertEqual(len(response.context['daily_stats']), 30)
        self.assertEqual(len(response.context['filtered_daily_stats']), 14)

    def test_no_ads_yet_renders_without_error(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['window_ctr'])
        self.assertIsNone(response.context['all_time_ctr'])


class AdSlotDimensionsTests(TestCase):
    def test_width_and_height_match_the_zone(self):
        ad = make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR_HALF_PAGE)
        self.assertEqual(ad.width, 300)
        self.assertEqual(ad.height, 600)

    def test_every_zone_has_dimensions_defined(self):
        for value, _label in AdSlot.Zone.choices:
            self.assertIn(value, AdSlot.ZONE_DIMENSIONS)


class AdSlotFormDimensionValidationTests(TestCase):
    """The actual fix for oversized/mismatched ad renders — see
    AdSlotForm.clean(). Direct ORM writes (make_ad, seed_demo_data) bypass
    this on purpose (fixtures/demos control their own image sizes); this is
    what an editor actually hits when creating or editing an ad in
    /manage/ads/.
    """

    def test_correctly_sized_image_is_accepted(self):
        form = AdSlotForm(data={
            'sponsor_name': 'Sponsor', 'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE_1,
            'link_url': 'https://example.com', 'start_date': timezone.localdate(), 'is_active': True,
        }, files={'image': demo_image(size=(300, 250))})
        self.assertTrue(form.is_valid(), form.errors)

    def test_wrong_sized_image_is_rejected(self):
        form = AdSlotForm(data={
            'sponsor_name': 'Sponsor', 'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE_1,
            'link_url': 'https://example.com', 'start_date': timezone.localdate(), 'is_active': True,
        }, files={'image': demo_image(size=(600, 200))})
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)
        self.assertIn('300×250', form.errors['image'][0])

    def test_error_names_the_zone_and_both_sizes(self):
        form = AdSlotForm(data={
            'sponsor_name': 'Sponsor', 'zone': AdSlot.Zone.HEADER_LEADERBOARD,
            'link_url': 'https://example.com', 'start_date': timezone.localdate(), 'is_active': True,
        }, files={'image': demo_image(size=(300, 250))})
        self.assertFalse(form.is_valid())
        message = form.errors['image'][0]
        self.assertIn('728×90', message)
        self.assertIn('300×250', message)


class AdSlotTemplateTagTests(TestCase):
    """ads.templatetags.ads_tags.ad_slot — the one call site every ad
    placement (header, mobile anchor, homepage, article page, ...) goes
    through. Uses a real page render (Home) rather than calling the tag
    function directly, so this also proves the tag is actually wired up in
    base.html/home.html, not just importable.
    """

    def test_active_ad_in_zone_renders_and_records_impression(self):
        ad = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Leaderboard Sponsor')
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'Leaderboard Sponsor')
        ad.refresh_from_db()
        self.assertEqual(ad.impression_count, 1)

    def test_ad_free_subscriber_does_not_see_header_ad(self):
        from billing.models import SubscriptionPlan, UserSubscription

        make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Leaderboard Sponsor')
        reader = User.objects.create_user(email='ad-tag-reader@example.com', password='pw', first_name='R', last_name='D')
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:home'))
        self.assertNotContains(response, 'Leaderboard Sponsor')

    def test_get_ad_for_request_returns_none_with_no_active_ad(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = User.objects.create_user(
            email='no-ad-reader@example.com', password='pw', first_name='N', last_name='R',
        )
        self.assertIsNone(get_ad_for_request(request, AdSlot.Zone.MOBILE_ANCHOR))


class AdPlaceholderTests(TestCase):
    """AdSettings.show_placeholder_when_empty (default off) — an "Advertise
    Here" box for an unsold zone instead of rendering nothing, toggled from
    /manage/ads/. Never shown to an ad-free (subscriber) reader regardless
    of the setting. Uses a real page render (Home, which has
    header_leaderboard/mobile_anchor/mobile_large_banner/homepage_rectangle_1
    zones with no AdSlot rows created in these tests) rather than calling
    the tag directly, matching AdSlotTemplateTagTests' approach.
    """

    def setUp(self):
        AdSettings.objects.all().delete()

    def test_placeholder_hidden_by_default(self):
        response = self.client.get(reverse('articles:home'))
        self.assertNotContains(response, 'ADVERTISE HERE')

    def test_placeholder_shown_when_enabled(self):
        settings_row = AdSettings.get_solo()
        settings_row.show_placeholder_when_empty = True
        settings_row.save()
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'ADVERTISE HERE')
        self.assertContains(response, 'Site Header — Leaderboard')

    def test_placeholder_never_shown_to_ad_free_subscriber(self):
        from billing.models import SubscriptionPlan, UserSubscription

        settings_row = AdSettings.get_solo()
        settings_row.show_placeholder_when_empty = True
        settings_row.save()
        reader = User.objects.create_user(
            email='placeholder-subscriber@example.com', password='pw', first_name='S', last_name='R',
        )
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:home'))
        self.assertNotContains(response, 'ADVERTISE HERE')

    def test_real_ad_takes_priority_over_placeholder(self):
        settings_row = AdSettings.get_solo()
        settings_row.show_placeholder_when_empty = True
        settings_row.save()
        make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Real Sponsor')
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'Real Sponsor')
        # Header leaderboard zone is filled — no placeholder for that zone —
        # but other empty zones on the same page should still show one.
        self.assertContains(response, 'ADVERTISE HERE')

    def test_get_solo_creates_row_on_first_access(self):
        self.assertEqual(AdSettings.objects.count(), 0)
        settings_row = AdSettings.get_solo()
        self.assertFalse(settings_row.show_placeholder_when_empty)
        self.assertEqual(AdSettings.objects.count(), 1)
        self.assertEqual(AdSettings.get_solo().pk, settings_row.pk)


class AdSettingsManageViewTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='ad-settings-editor@example.com', password='pw', first_name='E', last_name='D',
            role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(
            email='ad-settings-reader@example.com', password='pw', first_name='R', last_name='D',
        )

    def test_editor_can_toggle_placeholder_setting(self):
        self.client.force_login(self.editor)
        self.assertFalse(AdSettings.get_solo().show_placeholder_when_empty)
        response = self.client.post(reverse('ads:manage_ad_settings_toggle_placeholder'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AdSettings.get_solo().show_placeholder_when_empty)
        # Toggling again flips it back off.
        self.client.post(reverse('ads:manage_ad_settings_toggle_placeholder'))
        self.assertFalse(AdSettings.get_solo().show_placeholder_when_empty)

    def test_non_editor_cannot_toggle(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('ads:manage_ad_settings_toggle_placeholder'))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AdSettings.get_solo().show_placeholder_when_empty)

    def test_get_request_not_allowed(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ad_settings_toggle_placeholder'))
        self.assertEqual(response.status_code, 405)

    def test_toggle_button_shown_on_manage_list_page(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_adslot_list'))
        self.assertContains(response, 'Placeholders: OFF')
        settings_row = AdSettings.get_solo()
        settings_row.show_placeholder_when_empty = True
        settings_row.save()
        response = self.client.get(reverse('ads:manage_adslot_list'))
        self.assertContains(response, 'Placeholders: ON')
