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

    def test_crawlers_are_sent_on_but_not_counted(self):
        ad = make_ad()
        response = self.client.get(reverse('ads:click', args=[ad.pk]), HTTP_USER_AGENT='Googlebot/2.1')
        self.assertEqual(response.url, ad.link_url)
        ad.refresh_from_db()
        self.assertEqual(ad.click_count, 0)

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

    def test_reader_cannot_delete_ad(self):
        ad = make_ad()
        self.client.force_login(self.reader)
        response = self.client.post(reverse('ads:manage_adslot_delete', args=[ad.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(AdSlot.objects.filter(pk=ad.pk).exists())

    def test_editor_can_delete_ad(self):
        ad = make_ad()
        self.client.force_login(self.editor)
        response = self.client.post(reverse('ads:manage_adslot_delete', args=[ad.pk]))
        self.assertRedirects(response, reverse('ads:manage_adslot_list'))
        self.assertFalse(AdSlot.objects.filter(pk=ad.pk).exists())

    def test_delete_confirmation_page_shows_sponsor_name(self):
        ad = make_ad(sponsor_name='Acme Corp')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_adslot_delete', args=[ad.pk]))
        self.assertContains(response, 'Acme Corp')

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

    def test_search_filters_by_sponsor_name(self):
        match = make_ad(sponsor_name='Acme Pharma')
        make_ad(sponsor_name='Unrelated Sponsor')
        response = self.client.get(reverse('ads:manage_adslot_list'), {'q': 'acme'})
        self.assertEqual(list(response.context['ad_slots']), [match])

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


class AdSlotAnalyticsOverviewRedirectTests(TestCase):
    """The sitewide ad numbers moved to Analytics → Ads (admin_custom/analytics.py)."""

    def test_old_link_lands_on_analytics_ads_with_zone_and_period(self):
        editor = User.objects.create_user(email='ads-redirect@example.com', password='pw', first_name='E',
                                          last_name='D', role=User.Role.EDITOR)
        self.client.force_login(editor)
        response = self.client.get(reverse('ads:manage_ads_analytics'),
                                   {'filter_zone': AdSlot.Zone.HEADER_LEADERBOARD, 'chart_days': 90})
        self.assertRedirects(response, f"{reverse('admin_custom:analytics_ads')}?zone={AdSlot.Zone.HEADER_LEADERBOARD}&range=90",
                             fetch_redirect_response=False)

    def test_reader_cannot_use_it(self):
        reader = User.objects.create_user(email='ads-redirect-r@example.com', password='pw', first_name='R', last_name='D')
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('ads:manage_ads_analytics')).status_code, 403)


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


    def _form(self, size, zone=AdSlot.Zone.HEADER_LEADERBOARD, fmt='JPEG'):
        from django.core.files.uploadedfile import SimpleUploadedFile

        buffer = io.BytesIO()
        Image.new('RGB', size, (200, 40, 40)).save(buffer, format=fmt)
        upload = SimpleUploadedFile(f'ad.{fmt.lower()}', buffer.getvalue(), content_type=f'image/{fmt.lower()}')
        return AdSlotForm(data={
            'sponsor_name': 'Sponsor', 'zone': zone, 'link_url': 'https://example.com',
            'start_date': timezone.localdate(), 'is_active': True,
        }, files={'image': upload})

    def test_larger_copy_of_the_same_shape_is_accepted_and_kept_at_2x(self):
        form = self._form((2184, 270))  # 3× a 728×90 leaderboard
        self.assertTrue(form.is_valid(), form.errors)
        image = Image.open(form.cleaned_data['image'])
        self.assertEqual(image.size, (1456, 180))
        ad = form.save()
        self.assertEqual(Image.open(ad.image.path).size, (1456, 180))
        self.assertEqual((ad.width, ad.height), (728, 90))  # still shown at the zone size

    def test_2x_png_is_kept_as_it_is(self):
        form = self._form((600, 500), zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, fmt='PNG')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(Image.open(form.cleaned_data['image']).size, (600, 500))

    def test_off_by_a_pixel_shape_is_fine(self):
        self.assertTrue(self._form((2185, 270)).is_valid())

    def test_smaller_than_the_zone_is_refused_as_blurry(self):
        form = self._form((364, 45))
        self.assertFalse(form.is_valid())
        self.assertIn('blurry', form.errors['image'][0])
        self.assertIn('1456×180', form.errors['image'][0])

    def test_different_shape_is_refused_as_cut_off(self):
        form = self._form((1456, 400))
        self.assertFalse(form.is_valid())
        self.assertIn('cut off', form.errors['image'][0])

class AdSlotTemplateTagTests(TestCase):
    """ads.templatetags.ads_tags.ad_slot — the one call site every ad
    placement (header, mobile anchor, homepage, article page, ...) goes
    through. Uses a real page render (Home) rather than calling the tag
    function directly, so this also proves the tag is actually wired up in
    base.html/home.html, not just importable.
    """

    def test_active_ad_renders_with_its_seen_ping_but_counts_nothing_yet(self):
        # The page only carries the ad; the browser counts it once it is on screen.
        ad = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Leaderboard Sponsor')
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'Leaderboard Sponsor')
        self.assertContains(response, f'data-ad-seen="{reverse("ads:seen", args=[ad.pk])}"')
        ad.refresh_from_db()
        self.assertEqual(ad.impression_count, 0)

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

    def test_subscriber_on_a_plan_without_ad_free_perk_still_sees_ads(self):
        # is_ad_free_reader checks the reader's actual plan
        # (grants_ad_free_reading), not just "has any active subscription" —
        # this is the case that check now catches that a blanket "any
        # subscription" check couldn't.
        from billing.models import SubscriptionPlan, UserSubscription

        make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Leaderboard Sponsor')
        reader = User.objects.create_user(email='ad-tag-reader-2@example.com', password='pw', first_name='R', last_name='D')
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
            grants_ad_free_reading=False,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'Leaderboard Sponsor')

    def test_get_ad_for_request_returns_none_with_no_active_ad(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = User.objects.create_user(
            email='no-ad-reader@example.com', password='pw', first_name='N', last_name='R',
        )
        self.assertIsNone(get_ad_for_request(request, AdSlot.Zone.MOBILE_ANCHOR))


class AdPlaceholderTests(TestCase):
    """AdSettings.placeholder_zones (default empty) — an "Advertise Here"
    box for an unsold zone instead of rendering nothing, set per zone from
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

    def test_placeholder_shown_for_an_enabled_zone(self):
        settings_row = AdSettings.get_solo()
        settings_row.placeholder_zones = [AdSlot.Zone.HEADER_LEADERBOARD]
        settings_row.save()
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'ADVERTISE HERE')
        self.assertContains(response, 'Site Header — Leaderboard')

    def test_placeholder_not_shown_for_a_zone_not_enabled(self):
        settings_row = AdSettings.get_solo()
        settings_row.placeholder_zones = [AdSlot.Zone.MOBILE_ANCHOR]
        settings_row.save()
        response = self.client.get(reverse('articles:home'))
        self.assertNotContains(response, 'Site Header — Leaderboard')

    def test_placeholder_never_shown_to_ad_free_subscriber(self):
        from billing.models import SubscriptionPlan, UserSubscription

        settings_row = AdSettings.get_solo()
        settings_row.placeholder_zones = [AdSlot.Zone.HEADER_LEADERBOARD]
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
        settings_row.placeholder_zones = [AdSlot.Zone.HEADER_LEADERBOARD]
        settings_row.save()
        make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Real Sponsor')
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'Real Sponsor')
        self.assertNotContains(response, 'ADVERTISE HERE')

    def test_get_solo_creates_row_on_first_access(self):
        self.assertEqual(AdSettings.objects.count(), 0)
        settings_row = AdSettings.get_solo()
        self.assertEqual(settings_row.placeholder_zones, [])
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

    def test_editor_can_set_placeholder_zones(self):
        self.client.force_login(self.editor)
        self.assertEqual(AdSettings.get_solo().placeholder_zones, [])
        response = self.client.post(reverse('ads:manage_ad_settings_update_placeholder_zones'), {
            'placeholder_zones': [AdSlot.Zone.HEADER_LEADERBOARD, AdSlot.Zone.MOBILE_ANCHOR],
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(AdSettings.get_solo().placeholder_zones),
            {AdSlot.Zone.HEADER_LEADERBOARD, AdSlot.Zone.MOBILE_ANCHOR},
        )

    def test_unknown_zone_value_is_ignored(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('ads:manage_ad_settings_update_placeholder_zones'), {
            'placeholder_zones': [AdSlot.Zone.HEADER_LEADERBOARD, 'not-a-real-zone'],
        })
        self.assertEqual(AdSettings.get_solo().placeholder_zones, [AdSlot.Zone.HEADER_LEADERBOARD])

    def test_non_editor_cannot_update(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('ads:manage_ad_settings_update_placeholder_zones'), {
            'placeholder_zones': [AdSlot.Zone.HEADER_LEADERBOARD],
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AdSettings.get_solo().placeholder_zones, [])

    def test_get_request_not_allowed(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_ad_settings_update_placeholder_zones'))
        self.assertEqual(response.status_code, 405)

    def test_zone_checklist_shown_on_manage_list_page(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_adslot_list'))
        self.assertContains(response, '"Advertise Here" placeholders')
        self.assertContains(response, 'name="placeholder_zones"')


class GroupedSlotTests(TestCase):
    """Slots shown side by side (the homepage rectangle row, group='homepage_rectangles')
    never show one sponsor twice; the slot that would repeat collapses instead of
    offering itself as "Advertise Here"."""

    def setUp(self):
        AdSettings.objects.all().delete()

    def test_sponsor_fills_one_slot_of_the_row(self):
        first = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, sponsor_name='Dice')
        repeat = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_2, sponsor_name='  DICE ')
        other = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_3, sponsor_name='Annapurna Dental')
        settings_row = AdSettings.get_solo()
        settings_row.placeholder_zones = [AdSlot.Zone.HOMEPAGE_RECTANGLE_2]
        settings_row.save()
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, reverse('ads:click', args=[first.pk]))
        self.assertNotContains(response, reverse('ads:click', args=[repeat.pk]))
        self.assertContains(response, reverse('ads:click', args=[other.pk]))
        self.assertNotContains(response, 'ADVERTISE HERE')
        repeat.refresh_from_db()
        self.assertEqual(repeat.impression_count, 0)

    def test_other_zones_still_repeat_a_sponsor(self):
        header = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD, sponsor_name='Dice')
        rect = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, sponsor_name='Dice')
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, reverse('ads:click', args=[header.pk]))
        self.assertContains(response, reverse('ads:click', args=[rect.pk]))


class AdFreePagesTests(TestCase):
    """Sign-in, account and pitch pages carry no ads."""

    def test_login_register_and_pitch_pages_show_no_ad(self):
        header = make_ad(zone=AdSlot.Zone.HEADER_LEADERBOARD)
        anchor = make_ad(zone=AdSlot.Zone.MOBILE_ANCHOR)
        for name in ('users:login', 'users:register', 'users:password_reset', 'pitches:pitch_create'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertNotContains(response, reverse('ads:click', args=[header.pk]), msg_prefix=name)
            self.assertNotContains(response, reverse('ads:click', args=[anchor.pk]), msg_prefix=name)



class AdSeenTests(TestCase):
    """ads:seen — the impression, sent by the browser once the ad is on screen."""

    def test_seen_ping_counts_one_impression(self):
        from django.test import Client

        ad = make_ad()
        response = Client(enforce_csrf_checks=True).post(reverse('ads:seen', args=[ad.pk]))  # a beacon: no CSRF token
        self.assertEqual(response.status_code, 204)
        ad.refresh_from_db()
        self.assertEqual(ad.impression_count, 1)
        self.assertEqual(AdEvent.objects.filter(ad_slot=ad, event_type=AdEvent.EventType.IMPRESSION).count(), 1)

    def test_get_crawler_and_inactive_ad_count_nothing(self):
        ad = make_ad()
        inactive = make_ad(is_active=False)
        self.assertEqual(self.client.get(reverse('ads:seen', args=[ad.pk])).status_code, 405)
        self.client.post(reverse('ads:seen', args=[ad.pk]), HTTP_USER_AGENT='Googlebot/2.1')
        self.client.post(reverse('ads:seen', args=[inactive.pk]))
        ad.refresh_from_db()
        inactive.refresh_from_db()
        self.assertEqual((ad.impression_count, inactive.impression_count), (0, 0))
