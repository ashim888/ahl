"""Analytics split into one page per area (admin_custom/analytics.py):
Overview, Readership, Subscriptions, Ads, Newsletter — one shared period,
compared with the period before, only dated events counted, CSV per page."""
import csv
import datetime
import io

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from ads.models import AdEvent, AdSlot
from ads.services import record_click, record_impression
from articles.models import Article, ArticleView, Bookmark
from billing.models import SubscriptionPlan, UserSubscription
from newsletter.models import NewsletterIssue, Subscriber
from sections.models import Section
from users.models import User

from .analytics import Period, change, chart, parse_period

PAGES = ['admin_custom:analytics', 'admin_custom:analytics_readership', 'admin_custom:analytics_subscriptions',
         'admin_custom:analytics_ads', 'admin_custom:analytics_newsletter']


def user(role=User.Role.EDITOR, email='an-editor@example.com'):
    return User.objects.create_user(email=email, password='pw', first_name='A', last_name='B', role=role)


def days_ago(n, hour=12):
    return timezone.make_aware(datetime.datetime.combine(timezone.localdate() - datetime.timedelta(days=n),
                                                         datetime.time(hour)))


def view(article, n_days_ago=0, session='s1'):
    v = ArticleView.objects.create(article=article, session_key=session)
    ArticleView.objects.filter(pk=v.pk).update(viewed_at=days_ago(n_days_ago))


def ad_image():
    out = io.BytesIO()
    Image.new('RGB', (10, 10)).save(out, 'JPEG')
    return ContentFile(out.getvalue(), name='ad.jpg')


class PeriodTests(TestCase):
    def test_presets_custom_and_bad_input(self):
        today = timezone.localdate()
        period, error = parse_period({'range': '7'})
        self.assertEqual((period.start, period.end, period.days, error), (today - datetime.timedelta(days=6), today, 7, ''))
        self.assertEqual(parse_period({'range': '12'})[0].days, 30)  # unknown preset → 30 days
        period, _ = parse_period({'from': '2026-03-10', 'to': '2026-03-01'})  # swapped dates are fine
        self.assertEqual((period.start, period.end), (datetime.date(2026, 3, 1), datetime.date(2026, 3, 10)))
        self.assertTrue(parse_period({'from': 'nope', 'to': '2026-03-01'})[1])

    def test_previous_period_is_the_same_length_just_before(self):
        period = Period(datetime.date(2026, 3, 1), datetime.date(2026, 3, 10))
        self.assertEqual((period.previous.start, period.previous.end), (datetime.date(2026, 2, 19), datetime.date(2026, 2, 28)))

    def test_buckets_are_days_weeks_or_months(self):
        self.assertEqual(len(Period(datetime.date(2026, 3, 1), datetime.date(2026, 3, 30)).buckets()), 30)
        weeks = Period(datetime.date(2026, 1, 1), datetime.date(2026, 3, 31)).buckets()
        self.assertEqual((len(weeks), weeks[0].end), (13, datetime.date(2026, 1, 7)))
        months = Period(datetime.date(2025, 10, 10), datetime.date(2026, 10, 9)).buckets()
        self.assertEqual((len(months), months[0].start, months[0].end), (13, datetime.date(2025, 10, 10), datetime.date(2025, 10, 31)))
        self.assertEqual(sum((b.end - b.start).days + 1 for b in months), 365)

    def test_change_knows_whether_up_is_good(self):
        self.assertEqual(change(15, 10)['pct'], 50)
        self.assertTrue(change(15, 10)['good'])
        self.assertFalse(change(15, 10, up_is_good=False)['good'])
        self.assertTrue(change(3, 0)['new'])
        self.assertEqual(change(0, 0)['direction'], 'flat')

    def test_chart_scales_and_thins_labels(self):
        buckets = Period(datetime.date(2026, 3, 1), datetime.date(2026, 3, 30)).buckets()
        c = chart(buckets, [{'name': 'Views', 'color': '#000', 'values': list(range(30))}])
        self.assertEqual((c['top'], c['columns'][-1]['bars'][0]['pct'], c['series'][0]['total']), (29, 100, 435))
        self.assertLessEqual(sum(col['show_label'] for col in c['columns']), 11)


class AccessTests(TestCase):
    def test_editors_see_every_page_readers_and_visitors_dont(self):
        for name in PAGES:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)
        self.client.force_login(user(User.Role.VERIFIED_AUTHOR, 'reader@example.com'))
        for name in PAGES:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.client.force_login(user())
        for name in PAGES:
            response = self.client.get(reverse(name), {'range': 365})
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, 'aria-label="Analytics areas"')

    def test_money_only_for_senior_staff(self):
        self.client.force_login(user())
        response = self.client.get(reverse('admin_custom:analytics_subscriptions'))
        self.assertNotIn('revenue', response.context)
        self.assertNotContains(response, 'Subscription revenue')
        self.assertNotContains(self.client.get(reverse('admin_custom:analytics')), reverse('admin_custom:revenue'))
        self.client.force_login(user(User.Role.EDITOR_IN_CHIEF, 'eic@example.com'))
        self.assertContains(self.client.get(reverse('admin_custom:analytics_subscriptions')), 'Subscription revenue')


class ReadershipTests(TestCase):
    def setUp(self):
        self.client.force_login(user())
        self.health = Section.objects.create(name='Health', slug='health')
        self.story = Article.objects.create(title='Dengue rises', status=Article.Status.PUBLISHED, section=self.health,
                                            published_at=days_ago(2))
        self.other = Article.objects.create(title='Budget news', status=Article.Status.PUBLISHED, published_at=days_ago(60))

    def test_counts_this_period_against_the_previous_one(self):
        view(self.story, 1, 'a')
        view(self.story, 1, 'b')
        view(self.story, 2, 'a')
        view(self.other, 3, 'c')
        view(self.other, 40, 'd')  # previous 30-day period
        reader = User.objects.create_user(email='saver@example.com', password='pw', first_name='S', last_name='V')
        Bookmark.objects.create(user=reader, article=self.story)
        response = self.client.get(reverse('admin_custom:analytics_readership'))
        kpis = {k['label']: k for k in response.context['kpis']}
        self.assertEqual((kpis['Page views']['value'], kpis['Page views']['previous']), (4, 1))
        self.assertEqual(kpis['Unique readers']['value'], 3)
        self.assertEqual(kpis['Stories published']['value'], 1)
        self.assertEqual(kpis['Saved to reading lists']['value'], 1)
        top = response.context['top_stories']
        self.assertEqual([(s['article'], s['views'], s['readers'], s['saved'], s['new']) for s in top],
                         [(self.story, 3, 2, 1, True), (self.other, 1, 1, 0, False)])
        self.assertEqual(response.context['trend']['series'][0]['total'], 4)
        self.assertEqual(response.context['by_section'][0]['label'], 'Health')

    def test_section_filter_applies_to_everything(self):
        view(self.story, 1)
        view(self.other, 1)
        response = self.client.get(reverse('admin_custom:analytics_readership'), {'section': self.health.pk})
        self.assertEqual(response.context['kpis'][0]['value'], 1)
        self.assertEqual([s['article'] for s in response.context['top_stories']], [self.story])
        self.assertContains(response, f'range=7&amp;section={self.health.pk}')  # filters kept in the period links

    def test_no_lifetime_download_or_citation_figures(self):
        response = self.client.get(reverse('admin_custom:analytics_readership'))
        for text in ('Lifetime', 'Downloads', 'Citations'):
            self.assertNotContains(response, text)

    def test_csv(self):
        view(self.story, 1)
        response = self.client.get(reverse('admin_custom:analytics_readership'), {'range': 7, 'export': 'csv'})
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('analytics-readership-', response['Content-Disposition'])
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertIn(['Page views', '1', '0', ''], rows)
        self.assertTrue(any(row and row[0] == 'Dengue rises' for row in rows))


class SubscriptionTests(TestCase):
    def setUp(self):
        self.client.force_login(user(User.Role.EDITOR_IN_CHIEF, 'eic2@example.com'))
        self.plan = SubscriptionPlan.objects.create(name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
                                                    price=300, duration_days=30)
        self.today = timezone.localdate()

    def sub(self, email, start_days_ago, end_in_days, **extra):
        reader = User.objects.filter(email=email).first() or User.objects.create_user(
            email=email, password='pw', first_name='R', last_name='D')
        sub = UserSubscription.objects.create(user=reader, plan=self.plan, start_date=self.today - datetime.timedelta(days=start_days_ago),
                                              end_date=self.today + datetime.timedelta(days=end_in_days), **extra)
        UserSubscription.objects.filter(pk=sub.pk).update(created_at=days_ago(start_days_ago))
        return sub

    def test_started_cancelled_lapsed_renewed_and_trials(self):
        self.sub('new@example.com', 3, 27)
        self.sub('lapsed@example.com', 40, -10, status=UserSubscription.Status.EXPIRED)
        self.sub('renewed@example.com', 40, -10, status=UserSubscription.Status.EXPIRED)
        self.sub('renewed@example.com', 10, 20)
        self.sub('cancel@example.com', 5, 25, status=UserSubscription.Status.CANCELLED, cancelled_at=days_ago(4))
        trial = self.sub('trial@example.com', 6, 8, is_trial=True)
        self.sub('trial@example.com', 1, 29)  # converted
        response = self.client.get(reverse('admin_custom:analytics_subscriptions'))
        kpis = {k['label']: k['value'] for k in response.context['kpis']}
        self.assertEqual(kpis, {'New subscriptions': 4, 'Free trials started': 1, 'Cancelled': 1, 'Didn’t renew': 1})
        self.assertEqual(response.context['trials_converted'], 1)
        self.assertEqual(response.context['active_now'], 3)  # new, renewed, converted trial
        self.assertEqual(response.context['net_change'], 2)
        self.assertEqual(response.context['plans'][0]['active'], 3)
        self.assertTrue(trial.is_trial)

    def test_revoking_records_when(self):
        sub = self.sub('revoke@example.com', 1, 29)
        self.client.post(reverse('billing:manage_subscription_revoke', args=[sub.pk]))
        sub.refresh_from_db()
        self.assertEqual(sub.status, UserSubscription.Status.CANCELLED)
        self.assertIsNotNone(sub.cancelled_at)


class AdsTests(TestCase):
    def setUp(self):
        self.client.force_login(user())
        self.top = AdSlot.objects.create(sponsor_name='Top', zone=AdSlot.Zone.HEADER_LEADERBOARD, image=ad_image(),
                                         link_url='https://example.com')
        self.side = AdSlot.objects.create(sponsor_name='Side', zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, image=ad_image(),
                                          link_url='https://example.com')

    def test_period_figures_ctr_and_zone_filter(self):
        record_impression(self.top)
        record_impression(self.top)
        record_click(self.top)
        record_impression(self.side)
        old = AdEvent.objects.create(ad_slot=self.side, event_type=AdEvent.EventType.IMPRESSION)
        AdEvent.objects.filter(pk=old.pk).update(occurred_at=days_ago(45))
        response = self.client.get(reverse('admin_custom:analytics_ads'))
        kpis = {k['label']: k for k in response.context['kpis']}
        self.assertEqual((kpis['Impressions']['value'], kpis['Impressions']['previous'], kpis['Clicks']['value']), (3, 1, 1))
        self.assertEqual(kpis['Click-through rate']['display'], '33.33%')
        self.assertEqual([r['ad'] for r in response.context['ad_rows']], [self.top, self.side])
        response = self.client.get(reverse('admin_custom:analytics_ads'), {'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE_1})
        self.assertEqual(response.context['kpis'][0]['value'], 1)
        self.assertEqual([r['ad'] for r in response.context['ad_rows']], [self.side])
        self.assertEqual(response.context['zone_rows'], [])

    def test_ads_list_links_here(self):
        self.assertContains(self.client.get(reverse('ads:manage_adslot_list')), reverse('admin_custom:analytics_ads'))


class NewsletterTests(TestCase):
    def test_joined_left_confirm_rate_and_issues(self):
        self.client.force_login(user())
        Subscriber.objects.create(email='a@example.com', status=Subscriber.Status.CONFIRMED, confirmed_at=days_ago(2))
        Subscriber.objects.create(email='b@example.com', status=Subscriber.Status.PENDING)
        Subscriber.objects.create(email='c@example.com', status=Subscriber.Status.UNSUBSCRIBED, confirmed_at=days_ago(50),
                                  unsubscribed_at=days_ago(1))
        NewsletterIssue.objects.create(subject='Weekly', body_html='<p>x</p>', sent_at=days_ago(1), recipient_count=120)
        response = self.client.get(reverse('admin_custom:analytics_newsletter'))
        kpis = {k['label']: k['value'] for k in response.context['kpis']}
        self.assertEqual(kpis, {'New subscribers': 1, 'Unsubscribed': 1, 'Issues sent': 1, 'Emails delivered': 120})
        self.assertEqual((response.context['net_change'], response.context['confirmed_now']), (0, 1))
        self.assertEqual((response.context['sign_ups'], response.context['waiting']), (3, 1))
        self.assertContains(response, 'Weekly')


class OverviewTests(TestCase):
    def test_cards_link_to_each_page_and_old_export_still_works(self):
        self.client.force_login(user())
        response = self.client.get(reverse('admin_custom:analytics'), {'range': 7})
        self.assertEqual([c['title'] for c in response.context['cards']], ['Readership', 'Subscriptions', 'Ads', 'Newsletter'])
        for name in PAGES[1:]:
            self.assertContains(response, f'{reverse(name)}?range=7')
        self.assertContains(response, reverse('admin_custom:keyword_analytics'))
        export = self.client.get(reverse('admin_custom:analytics_csv_export'), {'range': 7})
        self.assertRedirects(export, f"{reverse('admin_custom:analytics')}?range=7&export=csv", fetch_redirect_response=False)
        csv_response = self.client.get(f"{reverse('admin_custom:analytics')}?range=7&export=csv")
        self.assertIn('Readership', csv_response.content.decode())

    def test_topics_page_shows_the_tabs(self):
        self.client.force_login(user())
        self.assertContains(self.client.get(reverse('admin_custom:keyword_analytics')), 'aria-label="Analytics areas"')
