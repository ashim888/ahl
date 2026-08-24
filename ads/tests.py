import datetime
import io

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from users.models import User

from .forms import AdSlotForm
from .models import AdEvent, AdSlot
from .services import get_ad_for_request, get_ad_for_zone, record_click, record_impression


def demo_image(name='ad.jpg', size=(10, 10)):
    buffer = io.BytesIO()
    Image.new('RGB', size).save(buffer, format='JPEG')
    return ContentFile(buffer.getvalue(), name=name)


def make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE, is_active=True, start_date=None, end_date=None, sponsor_name='Test Sponsor'):
    return AdSlot.objects.create(
        sponsor_name=sponsor_name, zone=zone, image=demo_image(), link_url='https://example.com/sponsor',
        is_active=is_active, start_date=start_date or timezone.localdate(), end_date=end_date,
    )


class AdSelectionTests(TestCase):
    def test_active_ad_in_zone_is_selected(self):
        ad = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE)
        self.assertEqual(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE), ad)

    def test_wrong_zone_is_not_selected(self):
        make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR)
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE))

    def test_inactive_ad_is_not_selected(self):
        make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE, is_active=False)
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE))

    def test_not_yet_started_ad_is_not_selected(self):
        make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE, start_date=timezone.localdate() + datetime.timedelta(days=1))
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE))

    def test_expired_ad_is_not_selected(self):
        make_ad(
            zone=AdSlot.Zone.HOMEPAGE_RECTANGLE,
            start_date=timezone.localdate() - datetime.timedelta(days=10),
            end_date=timezone.localdate() - datetime.timedelta(days=1),
        )
        self.assertIsNone(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE))

    def test_ad_with_no_end_date_runs_indefinitely(self):
        ad = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE, end_date=None)
        self.assertEqual(get_ad_for_zone(AdSlot.Zone.HOMEPAGE_RECTANGLE), ad)


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

    def test_list_view_includes_zone_stats(self):
        ad = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE)
        record_impression(ad)
        record_click(ad)
        self.client.force_login(self.editor)
        response = self.client.get(reverse('ads:manage_adslot_list'))
        homepage_stats = next(
            z for z in response.context['zone_stats'] if z['label'] == AdSlot.Zone.HOMEPAGE_RECTANGLE.label
        )
        self.assertEqual(homepage_stats['impressions'], 1)
        self.assertEqual(homepage_stats['clicks'], 1)
        self.assertEqual(homepage_stats['ctr'], 100.0)


class AdSlotListFilterTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='ad-filter-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_filters_by_zone(self):
        homepage_ad = make_ad(zone=AdSlot.Zone.HOMEPAGE_RECTANGLE, sponsor_name='Homepage Sponsor')
        make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR, sponsor_name='Sidebar Sponsor')
        response = self.client.get(reverse('ads:manage_adslot_list'), {'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE})
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


class AdSlotDimensionsTests(TestCase):
    def test_width_and_height_match_the_zone(self):
        ad = make_ad(zone=AdSlot.Zone.ARTICLE_SKYSCRAPER)
        self.assertEqual(ad.width, 160)
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
            'sponsor_name': 'Sponsor', 'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE,
            'link_url': 'https://example.com', 'start_date': timezone.localdate(), 'is_active': True,
        }, files={'image': demo_image(size=(300, 250))})
        self.assertTrue(form.is_valid(), form.errors)

    def test_wrong_sized_image_is_rejected(self):
        form = AdSlotForm(data={
            'sponsor_name': 'Sponsor', 'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE,
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
